#!/usr/bin/env python3
"""Check that registration events reached GA4 and show how they are attributed.

Uses the GA4 Data API. Requirements:
    pip install google-analytics-data
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
    The service account needs Viewer access on the GA4 property.

Usage:
    python3 scripts/verify_ga4_attribution.py <property_id>
    python3 scripts/verify_ga4_attribution.py <property_id> --days 30 --event registration \
        --expected 120

What it prints:
    1. registration events per day (did the Measurement Protocol calls land?)
    2. first-user source / medium / campaign for those events. This is the
       stitching working: first touch comes from the visitor's earlier site visit.
    3. session source for those events. Expect "(not set)": MP events carry no
       session-level source. That is normal, not a bug.

Exit code: 0 if events were found, 2 if none (GA4 standard reports can lag
24-48 hours, so re-run before concluding anything is broken).
"""

import argparse
import os
import sys

try:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Filter, FilterExpression, Metric, OrderBy, RunReportRequest,
    )
except ImportError:
    sys.exit("Install the client first: pip install google-analytics-data")


def run(client, prop, days, event, dims, order_by_date=False):
    req = RunReportRequest(
        property=f"properties/{prop}",
        date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="today")],
        dimensions=[Dimension(name=d) for d in dims],
        metrics=[Metric(name="eventCount")],
        dimension_filter=FilterExpression(filter=Filter(
            field_name="eventName",
            string_filter=Filter.StringFilter(value=event))),
        limit=100,
    )
    if order_by_date:
        req.order_bys = [OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name=dims[0]))]
    return client.run_report(req)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("property_id", help="GA4 property id (digits only)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--event", default="registration", help="event name sent by the handler")
    ap.add_argument("--expected", type=int, help="registrations expected in the window (from your export)")
    args = ap.parse_args()

    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        sys.exit("Set GOOGLE_APPLICATION_CREDENTIALS to your service account JSON path.")

    client = BetaAnalyticsDataClient()

    # 1. Did the events land?
    r = run(client, args.property_id, args.days, args.event, ["date"], order_by_date=True)
    total = 0
    print(f"=== '{args.event}' events per day (last {args.days} days) ===")
    for row in r.rows:
        n = int(row.metric_values[0].value)
        total += n
        print(f"  {row.dimension_values[0].value}  {n:>5}")
    print(f"  total: {total}")
    if args.expected:
        print(f"  expected from export: {args.expected}  ->  GA4 has {total / args.expected:.0%} of them")
        print("  (a big gap means the GA4 call is failing or was lost; check handler logs)")

    if not total:
        print("\nRESULT: no events found. Standard reports lag 24-48h; if older than that, "
              "run the handler with --dry-run and check validationMessages.")
        return 2

    # 2. First-touch attribution of those events (via the stitched client_id).
    r = run(client, args.property_id, args.days, args.event,
            ["firstUserSource", "firstUserMedium", "firstUserCampaignName"])
    print("\n=== first-user source / medium / campaign (discovery, via the stitched client_id) ===")
    direct = 0
    for row in sorted(r.rows, key=lambda x: -int(x.metric_values[0].value)):
        src, med, camp = (d.value for d in row.dimension_values)
        n = int(row.metric_values[0].value)
        if src in ("(direct)", "(not set)"):
            direct += n
        print(f"  {n:>5}  {src} / {med} / {camp}")
    print(f"\n  first-touch (direct)/(not set): {direct / total:.0%} of events")
    print("  Some of this is real direct traffic. A share that looks too high can mean cids are "
          "missing or wrong (phantom users get first-touch direct).")

    # 3. Session-level source, expected to be unset.
    r = run(client, args.property_id, args.days, args.event, ["sessionSource", "sessionMedium"])
    print("\n=== session source / medium (expected: mostly '(not set)') ===")
    for row in sorted(r.rows, key=lambda x: -int(x.metric_values[0].value)):
        src, med = (d.value for d in row.dimension_values)
        print(f"  {int(row.metric_values[0].value):>5}  {src} / {med}")

    print("\nRESULT: events found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
