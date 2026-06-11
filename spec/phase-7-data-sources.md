# Phase 7 — New data sources

**Status: planned.** Broadens what answers can be grounded in, ordered
cheapest-first. Each source reuses as much of the existing pipeline as possible.

**Outcome:** answers draw on material events, structured financials, and
governance documents — all cited the same way 10-Ks are today.

## Citation model (applies to every source)

Every filing/chunk/record carries a `source_type` and a canonical URL, so
citations stay uniform: "NVDA 8-K, 2025-08-20, [EDGAR link]" next to the
existing "AAPL 10-K 2024, Item 1A" cites. Widen `filings.form_type` from the
`'10-K'|'10-Q'` constraint as new types land.

## Sources, in build order

### 7.1 — 8-K filings (nearly free)

Material events: acquisitions, exec departures, guidance changes, restatements.
Same EDGAR submissions JSON, same download/clean/chunk/embed pipeline — mostly
just widening the form-type filter. 8-Ks are short and event-dated; store
`filed_at` prominently since "what happened recently" queries key on it.

### 7.2 — XBRL structured financials (free, high value)

EDGAR's `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` returns
every number the company ever reported (revenue, EPS, segments, margins) as
clean JSON — no HTML parsing. Build:

- `ingest/xbrl.py` — fetch + normalize companyfacts into a new
  `financial_facts` table: `(cik, concept, unit, fiscal_year, period, value,
  accession)`. Not embedded — this is structured data, queried by SQL.
- `get_financial_metric(ticker, concept, year?)` tool.

This is text-meets-numbers done properly and supercharges `compare_filings`
("risk language changed AND gross margin fell 3pts").

Token note: this is the most token-efficient feature in the system —
`get_financial_metric` returns one number instead of six chunks of MD&A text
that hopefully contain it. Prompt the model to prefer it for numeric questions.

### 7.3 — Proxy statements (DEF 14A)

Executive compensation, board composition, governance. Same pipeline as 8-K.

### 7.4 — Earnings call transcripts (deferred, paid)

Highest value for "what did management say about X", but there is no good free
source — requires a paid API (e.g. Financial Modeling Prep, API Ninjas). Defer
until everything free is in; when added, ingest as a new `source_type`
('transcript') through the same chunk/embed path.

## Definition of done

A question like "what material events did NVDA report this year, and how did
revenue compare to last year?" is answered citing an 8-K (with EDGAR link) and
XBRL-sourced numbers in one reply.
