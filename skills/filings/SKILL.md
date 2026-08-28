---
name: filings
description: Answer questions about what the companies a business depends on have disclosed to the SEC — material events, officer and auditor departures, restatements, defaults, quarterly results, and what any of it means given what the business has riding on them. Use for "what have our suppliers announced", "anything I should worry about", "did anything happen at X", "who left", "are any of our counterparties in trouble", or any question about filings, 8-Ks or counterparty risk.
---

# What your counterparties told the regulator

A public company has four business days to disclose a material event — a chief executive
leaving, a restatement, a covenant default, a major contract signed or lost. The filings
are free and machine-readable, and almost nobody reads them.

## Run a view

| The question | The view |
|---|---|
| What has happened? | `MaterialEvents` — ranked by consequence |
| Anything serious? | `ReadToday` — severity 3 only |
| Who left? | `GovernanceChanges` |
| How is each company doing? | `FilerActivity` |
| Everything, any form | `FilingsByForm` |
| What do the codes mean? | `ItemCatalog` |
| Write it up | `CounterpartyBriefing` — costs a model call |

Two scheduled agents run without being asked: `filingSweep` each morning, and
`filerCoverage` on Mondays.

## Four things to get right

**A filing is not a document.** An 8-K and its exhibits are indexed separately, so counting
documents double-counts every filing that had an attachment. The accession number is the
filing. Every view here already dedupes; a hand-written query will not.

**`filedOn` is not when it happened.** Four business days are allowed, so a Monday filing
may describe the previous Wednesday. Say "filed on", never "happened on".

**A ticker is not a company.** `entityName` is a NAME search, not a ticker lookup, and
tickers get retired and reissued — `NET` returns HEALTH NET INC unless the filer is keyed
by CIK. Every event view returns `edgarMatchedFiler`; if it does not name the company you
meant, the row is about somebody else. `filerCoverage` checks this across the whole list.

**Bound the window.** EDGAR's index reaches back to 2001, and ranking by consequence will
happily surface a 2012 auditor change above this month's news. Every event view takes
`sinceMonths`, defaulting to 18.

## Saying it properly

- **Most 8-K items are housekeeping**, and saying so is useful. A 9.01 is an exhibits
  attachment, a 5.07 is a shareholder vote. Do not dress routine disclosure up as a signal.
- **Lead with the exposure, not the filing.** "Our CRM of record just lost its CFO" lands;
  "Salesforce filed a 5.02" does not. The exposure note is in every row for this reason.
- **Severity is this realm's judgement**, published in `ItemCatalog` so it can be argued
  with. Say so if it is carrying the answer.
- **`ReadToday` returning nothing is a real and good answer.** Report it plainly.
- **US-listed filers only.** A company that does not file with the SEC is out of scope, not
  clean — never let its silence read as a good sign.
