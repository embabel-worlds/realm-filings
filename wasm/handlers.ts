/*
 * Scheduled agents over the filings.
 *
 * The reason this realm has a clock at all: an 8-K is a DEADLINE, not a
 * publication. A company has four business days to disclose, and once it has,
 * nothing announces it to you — the filing sits in an index that nobody opens.
 * By the time a supplier's restatement or a customer's CFO departure reaches the
 * trade press it is weeks old and somebody else has already acted on it.
 *
 * A handler reads the graph with ctx.gateway.cypher.query. There is no global
 * `gateway` here, and `gateway.kg.query` is the code_mode surface rather than
 * the wasm one. cypher_query takes no bound parameters, so the recency window
 * and every threshold are applied in TypeScript over a bounded read rather than
 * concatenated into the query string.
 */

type Row = Record<string, any>

async function read(ctx: any, cypher: string): Promise<Row[]> {
  const res = await ctx.gateway.cypher.query({ cypher })
  if (!res) return []
  if (Array.isArray(res)) return res
  if (Array.isArray(res.rows)) return res.rows
  if (res.data && Array.isArray(res.data.rows)) return res.data.rows
  return []
}

/* EDGAR dates are plain ISO days. */
function daysAgo(iso: string): number {
  const t = Date.parse(String(iso) + 'T00:00:00Z')
  return Number.isFinite(t) ? (Date.now() - t) / 86400000 : Number.POSITIVE_INFINITY
}

/*
 * The daily sweep. Everything the tracked companies have disclosed recently,
 * ranked by consequence and deduplicated to one row per FILING rather than one
 * per document — an 8-K and its exhibits are separately indexed, so a naive
 * count double-counts every filing that had an attachment.
 */
export async function filingSweep(args: { withinDays?: number; minSeverity?: number }, ctx: any) {
  const rows = await read(ctx, `
    MATCH (t:TrackedFiler)-[:HAS_FILING]->(f:Filing)
    WHERE f.form = '8-K' AND f.primaryItem IS NOT NULL
    MATCH (i:EightKItem {code: f.primaryItem})
    RETURN t.name AS company, t.ticker AS ticker, t.relationship AS theyAre,
           t.exposure AS exposure, f.accession AS accession, f.fileDate AS filedOn,
           f.displayName AS matchedFiler,
           i.code AS code, i.meaning AS meaning, i.category AS category, i.severity AS severity
    LIMIT 500
  `)

  const within = args && typeof args.withinDays === 'number' ? args.withinDays : 14
  const floor = args && typeof args.minSeverity === 'number' ? args.minSeverity : 2

  /* One row per filing. The accession IS the filing; the document is not. */
  const seen = new Set<string>()
  const recent = rows
    .filter(r => daysAgo(r.filedOn) <= within)
    .filter(r => Number(r.severity) >= floor)
    .filter(r => {
      const k = String(r.accession)
      if (seen.has(k)) return false
      seen.add(k)
      return true
    })
    .sort((a, b) =>
      Number(b.severity) - Number(a.severity) || String(b.filedOn).localeCompare(String(a.filedOn)))

  const serious = recent.filter(r => Number(r.severity) >= 3)
  const byCompany: Record<string, number> = {}
  for (const r of recent) byCompany[r.company] = (byCompany[r.company] || 0) + 1

  const top = serious[0] || recent[0] || null

  return {
    checkedAt: new Date().toISOString(),
    windowDays: within,
    filings: recent.length,
    seriousFilings: serious.length,
    companiesFiling: Object.keys(byCompany).length,
    byCompany,
    headline: top
      ? `${top.company} (${top.ticker}), our ${top.theyAre || 'counterparty'}, filed on ${top.filedOn}:` +
        ` ${top.meaning}` + (top.exposure ? ` We have riding on this: ${top.exposure}.` : '')
      : `Nothing above severity ${floor} filed by any tracked company in the last ${within} days.`,
    filingsList: recent.slice(0, 25),
  }
}

/*
 * Coverage, as a fact rather than a hope.
 *
 * Every number the sweep reports is conditional on the companies actually being
 * findable, and two things silently break that: a ticker with no filings in the
 * window (fine, quiet company) and a ticker that EDGAR resolved to a DIFFERENT
 * business, because tickers are retired and reissued. The second is the
 * dangerous one — it produces confident rows about a company you have never
 * heard of, correctly labelled, wholly irrelevant. This checks that the filer
 * EDGAR matched actually carries the ticker we asked for.
 */
export async function filerCoverage(args: {}, ctx: any) {
  const rows = await read(ctx, `
    MATCH (t:TrackedFiler)
    OPTIONAL MATCH (t)-[:HAS_FILING]->(f:Filing)
    RETURN t.ticker AS ticker, t.name AS name,
           count(DISTINCT f.accession) AS filings,
           max(f.fileDate) AS lastFiled,
           collect(DISTINCT f.displayName)[0..4] AS matchedFilers
    LIMIT 200
  `)

  const silent = rows.filter(r => Number(r.filings) === 0).map(r => r.ticker)
  const mismatched = rows.filter(r => {
    const names: string[] = (r.matchedFilers || []).filter(Boolean).map(String)
    if (!names.length) return false
    /* EDGAR writes the ticker in parentheses inside display_names. If none of
       the matched filers carries ours, the search found somebody else. */
    return !names.some(n => n.includes('(' + String(r.ticker) + ')'))
  })
  const stale = rows.filter(r => r.lastFiled && daysAgo(r.lastFiled) > 400)

  return {
    checkedAt: new Date().toISOString(),
    tickersTracked: rows.length,
    tickersWithNoFilings: silent,
    tickersWhoseFilerLooksWrong: mismatched.map(r => ({
      ticker: r.ticker, expected: r.name, edgarMatched: r.matchedFilers,
    })),
    tickersWithNothingRecent: stale.map(r => ({ ticker: r.ticker, lastFiled: r.lastFiled })),
    verdict: mismatched.length
      ? `${mismatched.length} ticker(s) resolved to a filer that does not carry that ticker — a reissued ` +
        'ticker matching an unrelated company. Treat their rows as suspect until checked.'
      : silent.length
        ? `${silent.length} ticker(s) returned no filings at all. Quiet, delisted, or not a US filer.`
        : 'Every tracked ticker resolved to a filer carrying that ticker, and all have filed.',
  }
}

/* Before the working day. An 8-K filed after yesterday's close is news this
   morning, and only this morning. */
defineSchedule('filingSweep', '0 0 7 * * *')
/* Weekly. A denominator changes when somebody adds a ticker, not hourly. */
defineSchedule('filerCoverage', '0 45 6 * * MON')
