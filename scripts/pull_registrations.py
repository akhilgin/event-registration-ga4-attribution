#!/usr/bin/env python3
"""Export Luma registrations for one event to CSV, decoding the encoded utm_source.

Environment:
    LUMA_API_KEY   your Luma API key (needs a Luma plan with API access)

Usage:
    python3 scripts/pull_registrations.py <event_id>
    python3 scripts/pull_registrations.py <event_id> --output out/ --answer "Company"

Output columns: guest_id, name, email, approval_status, registered_at,
checked_in_at, utm_source (raw), source, medium, campaign, cid, has_cid
(plus any registration questions passed with --answer).

The CSV contains registrant PII. It is git-ignored by default; keep it that way.
"""

import argparse
import csv
import os
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "handler"))
from webhook_handler import parse_encoded  # noqa: E402

API_BASE = "https://public-api.luma.com/v1"


def api_get(path, api_key, params=None, retries=5):
    url = API_BASE + path + ("?" + urlencode(params) if params else "")
    headers = {"x-luma-api-key": api_key, "Accept": "application/json"}
    for attempt in range(retries):
        try:
            with urlopen(Request(url, headers=headers)) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 5 * (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def get_all_guests(event_id, api_key):
    guests, cursor = [], None
    while True:
        params = {"event_id": event_id, "pagination_limit": "50"}
        if cursor:
            params["pagination_cursor"] = cursor
        data = api_get("/event/get-guests", api_key, params)
        guests.extend(data.get("entries", []))
        if not data.get("has_more"):
            break
        new_cursor = data.get("next_cursor")
        if new_cursor == cursor:
            print("Warning: cursor not advancing, stopping.", file=sys.stderr)
            break
        cursor = new_cursor
        time.sleep(0.5)
    return guests


def extract_answer(answers, label):
    for a in answers:
        if (a.get("label") or "").lower().strip() == label.lower().strip():
            val = a.get("answer", a.get("value", ""))
            if isinstance(val, list):
                return "; ".join(str(v) for v in val)
            if isinstance(val, dict):
                return str(val)
            return str(val).strip() if val else ""
    return ""


def guest_to_row(entry, answer_labels=()):
    g = entry.get("guest", {})
    raw = g.get("utm_source") or ""
    parsed = parse_encoded(raw)
    row = {
        "guest_id": g.get("api_id", ""),
        "name": g.get("name", ""),
        "email": g.get("email", ""),
        "approval_status": g.get("approval_status", ""),
        "registered_at": g.get("registered_at", ""),
        "checked_in_at": g.get("checked_in_at") or g.get("joined_at") or "",
        "utm_source": raw,
        # Explicit UTM fields from Luma win over positional ones in the encoded value.
        "source": parsed["source"] or "",
        "medium": g.get("utm_medium") or parsed["medium"] or "",
        "campaign": g.get("utm_campaign") or parsed["campaign"] or "",
        "cid": parsed["cid"] or "",
        "has_cid": bool(parsed["cid"]),
    }
    answers = g.get("registration_answers") or []
    for label in answer_labels:
        row[label] = extract_answer(answers, label)
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("event_id", help="Luma event API id")
    ap.add_argument("--output", default="out", help="output directory (default: out/)")
    ap.add_argument("--answer", action="append", default=[], metavar="LABEL",
                    help="also export this registration question (repeatable)")
    args = ap.parse_args()

    api_key = os.environ.get("LUMA_API_KEY")
    if not api_key:
        sys.exit("Set LUMA_API_KEY in your environment.")

    guests = get_all_guests(args.event_id, api_key)
    rows = [guest_to_row(g, args.answer) for g in guests]
    if not rows:
        print("No registrations found.")
        return

    os.makedirs(args.output, exist_ok=True)
    path = os.path.join(args.output, f"{args.event_id}_registrations.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with_cid = sum(1 for r in rows if r["has_cid"])
    with_utm = sum(1 for r in rows if r["utm_source"])
    print(f"Wrote {len(rows)} rows to {path}")
    print(f"  with a cid:        {with_cid} ({with_cid / len(rows):.0%})")
    print(f"  with any utm_source: {with_utm} ({with_utm / len(rows):.0%})")
    print("  (registrations without a cid usually came through a direct Luma link, not the site embed)")


if __name__ == "__main__":
    main()
