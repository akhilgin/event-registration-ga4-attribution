#!/usr/bin/env python3
"""Receive a registration webhook and forward it to GA4 via the Measurement Protocol.

Standalone, standard library only. Use this if you are not using Zapier.

The registration platform stores a UTM source of the form
    <original utm_source>__cid.<GA4 client_id>
(see embed/ga-cid-to-luma.js). This handler parses the client_id back out and
sends a `registration` event to GA4 using that client_id, which attaches the
event to the visitor's existing GA4 history.

Environment:
    GA4_MEASUREMENT_ID   e.g. G-XXXXXXXXXX
    GA4_API_SECRET       Measurement Protocol API secret (keep it out of the repo)
    WEBHOOK_TOKEN        optional; if set, requests must include ?token=<value>

Usage:
    # Try the parser without any network call
    python3 webhook_handler.py --parse "google__cpc__spring__cid.1234567890.1700000000"

    # Run the receiver, validating against GA4's debug endpoint (nothing is recorded)
    python3 webhook_handler.py --serve --port 8080 --dry-run

    # Run the receiver for real
    python3 webhook_handler.py --serve --port 8080

The webhook payload shape differs between platforms. This handler looks for a
`utm_source` key anywhere in the JSON body (and utm_medium / utm_campaign /
utm_term / utm_content if present). Check your platform's payload and adjust
find_key() calls if needed.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

MP_URL = "https://www.google-analytics.com/mp/collect"
MP_DEBUG_URL = "https://www.google-analytics.com/debug/mp/collect"

# `cid.<digits>.<digits>` at the start of the string or after an underscore.
# Matched by prefix, anywhere in the string. Never by split position.
CID_RE = re.compile(r"(?:^|_)cid\.(\d+\.\d+)(?![\d.])")

# Positional names for the remaining `__`-separated tokens.
FIELDS = ("source", "medium", "campaign", "term", "content")


def parse_encoded(encoded):
    """Parse '<utm parts>__cid.<client_id>' into a dict.

    Returns {"cid", "source", "medium", "campaign", "term", "content"}.
    Any value that is not present is None. `cid` is None if no valid client_id
    is found, in which case the caller should NOT send anything to GA4.
    """
    result = {"cid": None, **{f: None for f in FIELDS}}
    if not isinstance(encoded, str) or not encoded.strip():
        return result
    text = encoded.strip()

    match = CID_RE.search(text)
    if match:
        result["cid"] = match.group(1)
        text = text[: match.start()] + "__" + text[match.end():]

    tokens = [t.strip("_ ") for t in re.split(r"_{2,}", text)]
    tokens = [t for t in tokens if t]
    for field, token in zip(FIELDS, tokens):
        result[field] = token
    return result


def find_key(obj, key):
    """Return the first value for `key` found anywhere in nested dicts/lists."""
    if isinstance(obj, dict):
        if obj.get(key):
            return obj[key]
        for value in obj.values():
            found = find_key(value, key)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_key(item, key)
            if found:
                return found
    return None


def build_payload(parsed, event_name="registration", extra_params=None):
    """Build the Measurement Protocol body. Requires parsed['cid']."""
    params = {"engagement_time_msec": 1}
    # Reserved MP parameter names. `utm_source` / `utm_medium` are ignored by GA4.
    for field in FIELDS:
        if parsed.get(field):
            params[field] = parsed[field]
    params.update(extra_params or {})
    return {
        "client_id": parsed["cid"],
        "events": [{"name": event_name, "params": params}],
    }


def send_to_ga4(payload, measurement_id, api_secret, debug=False, timeout=10):
    """POST the payload. Returns (http_status, parsed_json_or_None)."""
    base = MP_DEBUG_URL if debug else MP_URL
    url = base + "?" + urllib.parse.urlencode(
        {"measurement_id": measurement_id, "api_secret": api_secret}
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode() or ""
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def process_webhook(body, measurement_id, api_secret, debug=False, event_name="registration"):
    """Handle one parsed webhook body. Returns a small result dict."""
    encoded = find_key(body, "utm_source")
    parsed = parse_encoded(encoded)

    # Explicit UTM fields from the platform win over positional ones.
    for field in FIELDS[1:]:
        explicit = find_key(body, "utm_" + field)
        if explicit:
            parsed[field] = explicit

    if not parsed["cid"]:
        return {"sent": False, "reason": "no cid found; not sending to GA4"}

    payload = build_payload(parsed, event_name=event_name)
    status, debug_body = send_to_ga4(payload, measurement_id, api_secret, debug=debug)
    result = {"sent": 200 <= status < 300, "status": status, "client_id": parsed["cid"]}
    if debug:
        result["validation"] = (debug_body or {}).get("validationMessages", [])
        result["sent"] = False  # the debug endpoint never records events
        result["validated"] = status == 200 and not result["validation"]
    return result


def make_handler(measurement_id, api_secret, debug, token, event_name):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if token and query.get("token", [""])[0] != token:
                return self._reply(401, {"error": "bad token"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._reply(400, {"error": "invalid JSON"})
            result = process_webhook(body, measurement_id, api_secret, debug, event_name)
            print(json.dumps(result), flush=True)  # no registrant data in the log line
            # Always 200 for a well-formed request so the sender does not retry
            # registrations that simply had no cid.
            self._reply(200, result)

        def log_message(self, *args):  # silence default per-request logging
            pass

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--parse", metavar="ENCODED", help="parse one encoded utm_source and print JSON")
    ap.add_argument("--serve", action="store_true", help="run the webhook receiver")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--event-name", default="registration")
    ap.add_argument(
        "--dry-run", "--debug", dest="debug", action="store_true",
        help="send to GA4's /debug/mp/collect validation endpoint (events are NOT recorded)",
    )
    args = ap.parse_args(argv)

    if args.parse is not None:
        print(json.dumps(parse_encoded(args.parse), indent=2))
        return 0
    if not args.serve:
        ap.print_help()
        return 1

    measurement_id = os.environ.get("GA4_MEASUREMENT_ID")
    api_secret = os.environ.get("GA4_API_SECRET")
    if not measurement_id or not api_secret:
        print("Set GA4_MEASUREMENT_ID and GA4_API_SECRET.", file=sys.stderr)
        return 1

    handler = make_handler(
        measurement_id, api_secret, args.debug, os.environ.get("WEBHOOK_TOKEN"), args.event_name
    )
    mode = "DRY RUN (debug endpoint)" if args.debug else "LIVE"
    print(f"Listening on {args.host}:{args.port} [{mode}]", flush=True)
    HTTPServer((args.host, args.port), handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
