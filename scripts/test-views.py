#!/usr/bin/env python3
"""Run every view this realm ships against a LIVE host, and check its guarantees.

Row counts are not the interesting failure. This realm's characteristic bugs all
produce a FULL, plausible table that is about the wrong thing:

  * a reissued ticker returning another company's filings, correctly labelled;
  * an ancient severe filing outranking this month's news;
  * one filing counted several times because its exhibits are indexed separately;
  * an item code decoded against nothing, so the meaning silently disappears.

Each is asserted below. A harness that only counted rows would pass on all four.

    export EMBABEL_TOKEN=...
    python3 scripts/test-views.py [http://127.0.0.1:11043]
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:11043").rstrip("/")
TOKEN = os.environ.get("EMBABEL_TOKEN")

WINDOW = 18
VIEWS = {
    "MaterialEvents":       {"limit": 60, "sinceMonths": WINDOW},
    "ReadToday":            {"limit": 40, "sinceMonths": WINDOW},
    "GovernanceChanges":    {"limit": 40, "sinceMonths": WINDOW},
    "FilerActivity":        {"limit": 60, "sinceMonths": WINDOW},
    "ItemCatalog":          {"limit": 40},
    "FilingsByForm":        {"limit": 80, "sinceMonths": WINDOW},
    "CounterpartyBriefing": {"limit": 20, "sinceMonths": WINDOW},
}

# Empty is a legitimate — indeed desirable — answer only here.
MAY_BE_EMPTY = {
    "ReadToday": "no bankruptcy, restatement, default or auditor change is the outcome you want",
    "GovernanceChanges": "a window in which nobody senior moved is entirely normal",
}

failures, notes = [], []


def run_view(name, params):
    req = urllib.request.Request(
        f"{BASE}/api/v1/admin/kg/views/{name}/run",
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def check_views():
    results = {}
    for name, params in VIEWS.items():
        try:
            res = run_view(name, params)
        except urllib.error.HTTPError as e:
            failures.append(f"{name}: HTTP {e.code} {e.read()[:200]!r}")
            continue
        except Exception as e:  # noqa: BLE001 — a harness reports; it does not raise
            failures.append(f"{name}: {e}")
            continue
        results[name] = res
        rows, warns = res.get("rows") or [], res.get("warnings") or []
        if not rows and name not in MAY_BE_EMPTY:
            failures.append(f"{name}: ZERO ROWS — a join that never fires looks exactly like this")
        for w in warns:
            notes.append(f"{name}: {str(w)[:200]}")
        why = f"  ({MAY_BE_EMPTY[name]})" if not rows and name in MAY_BE_EMPTY else ""
        print(f"  {name:<22}{len(rows):>4} rows{why}")
    return results


def check_ground_truth(results):
    cutoff = (date.today() - timedelta(days=WINDOW * 31)).isoformat()

    # 1. Nothing outside the requested window.
    for name in ("MaterialEvents", "ReadToday", "GovernanceChanges", "FilingsByForm"):
        for row in (results.get(name) or {}).get("rows") or []:
            filed = row.get("filedOn")
            if filed and filed < cutoff:
                failures.append(
                    f"ground truth: {name} returned a filing dated {filed}, outside the "
                    f"{WINDOW}-month window — the recency filter is not being applied"
                )
    print(f"  no filing falls outside the {WINDOW}-month window")

    # 2. THE trap: the filer EDGAR matched must carry the ticker we asked for.
    #    A reissued ticker returns another company's real filings, correctly labelled.
    for row in (results.get("MaterialEvents") or {}).get("rows") or []:
        matched, ticker = row.get("edgarMatchedFiler"), row.get("ticker")
        if matched and ticker and f"({ticker})" not in matched:
            failures.append(
                f"ground truth: {row.get('company')} was asked for as {ticker} but EDGAR matched "
                f"'{matched}' — a reissued ticker matching an unrelated company"
            )
    print("  every filing belongs to the company that was asked for")

    # 3. Every decoded item must exist in the shipped catalog.
    catalog = {r["code"] for r in (results.get("ItemCatalog") or {}).get("rows") or []}
    if not catalog:
        failures.append("ground truth: the EightKItem catalog is EMPTY — reference data did not seed")
    for row in (results.get("MaterialEvents") or {}).get("rows") or []:
        code = row.get("itemCode")
        if code and code not in catalog:
            failures.append(f"ground truth: item {code} was decoded but is not in the catalog")
        if code and not row.get("whatHappened"):
            failures.append(f"ground truth: item {code} decoded to an empty meaning")
    print(f"  every decoded item resolves against the catalog ({len(catalog)} codes)")

    # 4. A filing must not be counted twice. The accession IS the filing.
    for name in ("MaterialEvents", "ReadToday"):
        seen = {}
        for row in (results.get(name) or {}).get("rows") or []:
            k = (row.get("accession"), row.get("itemCode"))
            seen[k] = seen.get(k, 0) + 1
        dupes = [k for k, n in seen.items() if n > 1]
        if dupes:
            failures.append(
                f"ground truth: {name} returned {len(dupes)} duplicated accession/item pair(s) — "
                f"exhibits are being counted as separate filings, e.g. {dupes[0]}"
            )
    print("  filings are counted once, not once per document")

    # 5. Severity must be one of the three the catalog defines.
    for row in (results.get("MaterialEvents") or {}).get("rows") or []:
        if row.get("severity") not in (1, 2, 3):
            failures.append(f"ground truth: severity {row.get('severity')!r} is outside 1-3")
    print("  severities are within the catalog's own scale")


def main():
    if not TOKEN:
        sys.exit("EMBABEL_TOKEN is not set — this harness needs an admin bearer token. It refuses "
                 "to run rather than report a green that only means it never asked.")
    print(f"realm-filings against {BASE}\n\nviews:")
    results = check_views()
    print("\nground truth:")
    check_ground_truth(results)

    if notes:
        print("\nwarnings from the host — read these; an empty table here reads as 'nothing happened':")
        for n in notes:
            print(f"  {n}")
    if failures:
        print(f"\nFAILED ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    print("\nOK — every view answered and every guarantee holds.")


if __name__ == "__main__":
    main()
