# realm-filings

**What the companies you depend on just told their regulator.**

```
TrackedFiler ──HAS_FILING──▶ Filing        fetched per EDGAR key
Filing.primaryItem ───────── EightKItem    a catalog this realm ships as data
```

A public company cannot quietly change its chief executive, restate its accounts, default
on a covenant or lose a major contract: within four business days it must file an 8-K
saying so. Those filings are free and machine-readable, and almost nobody watches them — so
a supplier's going-concern warning reaches you through the trade press weeks later, if at
all.

Live, from four suppliers seeded as a test:

> **Salesforce (CRM), our supplier, filed on 2026-08-05: a director or senior officer
> departed, was removed, or was appointed.** We have riding on this: CRM of record; a
> migration would take two quarters.

## The catalog is data, not a CASE statement

An 8-K's payload is a list of item codes, and the codes *are* the information: `5.02` is a
senior officer leaving, `4.02` is the company saying its own past accounts cannot be relied
on. That vocabulary ships in `reference/` as ordinary graph data — 22 codes, each with a
plain-English meaning, a category, and a severity the views rank by.

The severity is **this realm's judgement**, not an SEC classification, and it lives in a
file precisely so it can be argued with: a lender and a procurement team would score "took
on a material financial obligation" differently, and either can edit it without touching a
query.

## Three traps, all of which produce confident wrong answers

**A ticker is not a company.** EDGAR's `entityName` is a NAME search. `SNOW`, `CRM` and
`MDB` resolve cleanly because those strings are distinctive; `NET` returns *HEALTH NET INC*
and *MARKETCENTRAL NET CORP* — real filings, correctly labelled, about companies nobody was
asking about. So the join key is `edgarKey`: give it a ticker for convenience or a
zero-padded CIK for certainty, and run `filerCoverage`, which flags any filer that does not
carry the ticker you expected. (An *unpadded* CIK matches nothing at all, silently.)

**A filing is not a document.** An 8-K and its exhibits are separately indexed, so a naive
count double-counts every filing with an attachment. The accession is the filing; `_id` is
the document. Every view dedupes on accession.

**An old severe filing is not news.** EDGAR reaches back to 2001, and ranking by consequence
put a 2012 auditor change above this month's events until every view gained a `sinceMonths`
window, computed at query time so it never goes stale.

## A limit worth knowing

EDGAR returns several fields as ARRAYS — `items`, `display_names`, `ciks` — and a projection
of a whole array arrives **null**, not as a list property. A trailing index does resolve, so
the item codes are taken by position as `primaryItem` and `secondaryItem`. An 8-K orders its
substantive disclosure first and its `9.01` exhibits attachment last, so those two slots
carry the story in the overwhelming majority of filings — but a filing disclosing three or
more substantive items will under-report, which is why the field is named `primaryItem`
rather than implying completeness.

## Getting an answer

```javascript
gateway.repository.createEntry({ type: "TrackedFiler", data: {
  ticker: "SNOW", edgarKey: "SNOW", name: "Snowflake", relationship: "supplier",
  exposure: "our primary data warehouse — a pricing or leadership shock lands on us",
}})
```

Then run `MaterialEvents`, or open **Filed** (`apps/filed.html`).

## Testing

```bash
export EMBABEL_TOKEN=...
python3 scripts/test-views.py http://127.0.0.1:11043
```

Runs every view, fails on zero rows, surfaces every warning, and checks the guarantees: that
no filing falls outside the requested window, that every decoded item exists in the catalog,
that accessions are not double-counted, and that the filer EDGAR matched carries the ticker
that was asked for.

## Licence

Apache 2.0. Filing data is US Government public domain, via the SEC's EDGAR service.
