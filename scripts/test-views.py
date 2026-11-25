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


# A figure the engine marks short is not the realm's figure, and a battery that counts it reports
# drift that is the source's. short(d) reads an answer's own error, reason, warnings and outcome and
# is None when the answer is whole, else the line that stands in for the figure: "REFUSED: <why>"
# or "PARTIAL <n>: <the engine's reason>". It reads both wires: a query answer (`rows`, `warnings`
# as strings opening with the engine's code) and a view envelope (`status`, `outcome`, `warnings`
# as {code, message}).
# Raw warning codes that mean rows or values may be missing (the engine's incompleteness kinds).
# Cost notes (FILTERED_IN_GRAPH, AGGREGATE_NOT_PUSHED, EMPTY_NOT_KEPT, PUSHDOWN_VALUE_UNMATCHED),
# FILTER_STARVED (an honest empty), STALE_COPY, FIELDS_WITHHELD and UNKNOWN_VIA leave every row in place.
SHORT_CODES = (
    "PARTIAL_RESULT", "PRODUCER_ERROR", "NEEDS_FILTER", "NEEDS_PRODUCER", "FILTER_REJECTED",
    "UNPUSHED_FILTER", "AMBIGUOUS_LABEL", "INCOMPLETE_TRAVERSAL", "INCOMPLETE_RANKING",
    "INCOMPLETE_AGGREGATE", "INCOMPLETE_INPUT", "MATERIALIZATION_FAILED", "REDUCTION_FAILED",
    "UNPARSEABLE_ANSWER", "TERMS_UNAVAILABLE", "COMPUTE_FAILED", "PROPERTY_NOT_STORED",
    "FOLLOW_CAPPED", "UNLINKED_CHILDREN", "RESOLUTION_DROPPED", "AGENTIC_DEGRADED",
    "SOURCE_UNANSWERED",
)
# The typed `reason` a query result carries when it is not a clean answer and not an honest empty.
SHORT_REASONS = ("UNBOUNDED", "PARTIAL_NOT_MATCHED", "UNPUSHED_FILTER", "DISCONNECTED",
                 "INTERNAL_ERROR", "WRITE_IN_PROGRESS", "KILLED", "TOO_EXPENSIVE")
# Public warning codes on a view envelope that mean the same.
SHORT_PUBLIC = ("PARTIAL", "REDUCTION_FAILED", "COMPUTE_FAILED", "PROPERTY_NOT_STORED",
                "AGENTIC_DEGRADED", "RATE_LIMITED", "SOURCE_UNAVAILABLE", "SOURCE_REJECTED",
                "INVALID_FILTER", "UNPUSHED_FILTER", "TOO_BROAD", "FETCH_CAPPED",
                "INDEX_UNAVAILABLE", "ARGUMENT_REFUSED")


def short(d, figure=None):
    tag = "PARTIAL" if figure is None else "PARTIAL %s" % (figure,)
    if not isinstance(d, dict):
        return "REFUSED: not an engine answer: " + str(d)[:160]
    if "outcome" in d or "status" in d:  # a view envelope
        err = d.get("error") or {}
        if d.get("status") != "SUCCEEDED":
            return "REFUSED: %s %s" % (d.get("status"), (err.get("code", "") + " " + err.get("message", "")).strip()[:160] if isinstance(err, dict) else str(err)[:160])
        ws = [w for w in d.get("warnings") or [] if isinstance(w, dict) and w.get("code") in SHORT_PUBLIC]
        if d.get("outcome") not in ("OK", "EMPTY") or ws:
            why = ws[0]["code"] + ": " + ws[0].get("message", "") if ws else "outcome " + str(d.get("outcome"))
            return "%s: %s" % (tag, why[:200])
        return None
    if d.get("error"):
        return "REFUSED: " + str(d["error"])[:160]
    if d.get("run"):
        return "%s: the run had not finished (%s)" % (tag, d["run"])
    ws = [w for w in d.get("warnings") or [] if isinstance(w, str) and w.split(":", 1)[0].strip() in SHORT_CODES]
    if ws:
        return "%s: %s" % (tag, ws[0][:200])
    if d.get("reason") in SHORT_REASONS:
        return "%s: reason %s" % (tag, d["reason"])
    return None


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
        # A warning that says rows are missing fails the view: its table is not the answer, however
        # plausible it looks. Every other warning stays a note to read.
        s = short(res, len(rows))
        if s:
            failures.append(f"{name}: {s}")
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
