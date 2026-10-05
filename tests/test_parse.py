"""Parsing tests. Run from the repo root:  python3 -m unittest discover -s tests -v

The same cases (tests/parse_cases.json) are run against the Python handler and,
if Node is installed, against the Zapier step and the browser script.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "handler"))

from webhook_handler import build_payload, find_key, parse_encoded, process_webhook  # noqa: E402

with open(os.path.join(HERE, "parse_cases.json")) as f:
    CASES = json.load(f)


class ParseCases(unittest.TestCase):
    def test_shared_cases(self):
        for case in CASES:
            with self.subTest(case["name"]):
                got = parse_encoded(case["input"])
                for key in ("cid", "source", "medium", "campaign", "term", "content"):
                    if key in case:
                        self.assertEqual(got[key], case[key], f"{key} for {case['input']!r}")


class ParseBehaviour(unittest.TestCase):
    def test_cid_position_does_not_matter(self):
        a = parse_encoded("x__cid.1234567890.1700000000")["cid"]
        b = parse_encoded("cid.1234567890.1700000000__x")["cid"]
        c = parse_encoded("x__y__z__cid.1234567890.1700000000")["cid"]
        d = parse_encoded("x__cid.1234567890.1700000000__y__z")["cid"]
        self.assertEqual({a, b, c, d}, {"1234567890.1700000000"})

    def test_non_string_input(self):
        for bad in (None, 5, [], {}):
            self.assertIsNone(parse_encoded(bad)["cid"])

    def test_extra_tokens_are_ignored(self):
        got = parse_encoded("a__b__c__d__e__f__g__cid.1234567890.1700000000")
        self.assertEqual(got["content"], "e")


class Payload(unittest.TestCase):
    def test_uses_reserved_param_names(self):
        parsed = parse_encoded("google__cpc__spring__cid.1234567890.1700000000")
        payload = build_payload(parsed)
        params = payload["events"][0]["params"]
        self.assertEqual(payload["client_id"], "1234567890.1700000000")
        self.assertEqual(payload["events"][0]["name"], "registration")
        self.assertEqual((params["source"], params["medium"], params["campaign"]),
                         ("google", "cpc", "spring"))
        self.assertNotIn("utm_source", params)
        self.assertNotIn("utm_medium", params)

    def test_no_cid_means_no_send(self):
        # Would raise on a network call with these bogus credentials if it tried to send.
        result = process_webhook({"guest": {"utm_source": "linkedin"}}, "G-TEST", "secret")
        self.assertFalse(result["sent"])
        self.assertIn("no cid", result["reason"])

    def test_find_key_nested(self):
        body = {"data": {"guest": [{"x": 1}, {"utm_source": "a__cid.1234567890.1700000000"}]}}
        self.assertEqual(find_key(body, "utm_source"), "a__cid.1234567890.1700000000")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class JavaScript(unittest.TestCase):
    def test_js_matches_python(self):
        proc = subprocess.run(["node", os.path.join(HERE, "test_js.js")],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
