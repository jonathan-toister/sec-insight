# Phase 8 — Structured financials (XBRL)

**Status: planned.** First *additive* phase and the foundation for all
quantitative analysis. The 10-K text is the worst place to get numbers; SEC's
XBRL API hands them over as clean JSON, no parsing. This supersedes the old
Phase 7.2 sketch with a dedicated phase.

**Outcome:** financial metrics are rows queried by SQL, not text retrieved from
chunks — the most token-efficient feature in the system. A numeric question
returns one value with a citation instead of six chunks of MD&A.

## Source

- **XBRL Company Facts:** `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
  — every value the company ever reported. Same User-Agent + rate-limit rules
  as existing EDGAR calls.
- **XBRL Frames:** `https://data.sec.gov/api/xbrl/frames/...` — one concept
  across all filers for a period. Powers peer aggregates in Phase 11.

## Build

1. **`metric_dimensions` table** — `(xbrl_tag, canonical_name, statement, sign,
   unit_expected)`. XBRL exposes many tags for the same idea (e.g. several
   "revenue" concepts); this mapping collapses them to one canonical metric so
   models and peer comparisons don't fracture. Seed with the metrics the
   valuation engine needs (revenue, net income, EPS, FCF components, total
   assets/liabilities, equity, shares outstanding, dividends).

2. **`financial_facts` table** — `(company_id, filing_id, accession,
   fiscal_period, period_end, filed_at, metric_canonical, xbrl_tag, value,
   unit)`. Not embedded. `filed_at`/`period_end` carry the Phase 6 point-in-time
   contract so facts are usable "as of" a date. Link `filing_id` for citations.

3. **`ingest/xbrl.py`** — fetch companyfacts, map tags via `metric_dimensions`,
   upsert facts. Idempotent on `(company_id, metric_canonical, fiscal_period,
   accession)`.

4. **`get_financials(ticker, metric?, period?)` tool** — returns canonical
   metrics with their source filing for citation. Prompt the agent to prefer it
   over text retrieval for any numeric question.

## Definition of done

Revenue, EPS, and free-cash-flow components for a real company return from
`financial_facts` via SQL, each citing the originating filing, with point-in-time
fields populated.
