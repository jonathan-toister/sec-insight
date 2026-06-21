# Phase 6 — Schema hardening + data integrity

**Status: planned.** Pure refactor of the current tables — no new capability,
no new data source. It lands first because every later phase (valuation,
sectors, events) joins against companies/filings/chunks, and those joins are
only trustworthy if the keys, dates, and provenance are right.

**Sprint note:** implement Phase 6 and Phase 7 together as one sprint. They
share a backfill step and both produce foundational changes before any new
capability lands in Phase 8+.

**Outcome:** the existing five tables become analysis-ready: every fact is
attributable to a filing, dated by *period* and *filing time*, and queryable
"as of" any date without lookahead bias.

## Build

1. **`companies` — sector mapping.** The table already has `cik`, `sic`,
   `sic_description`. Add `sector` and `industry` (a normalized,
   GICS-style label derived from `sic`) and `fiscal_year_end`. Keep `sic` as the
   raw source of truth; `sector`/`industry` are the analysis-facing labels
   Phase 11 builds on. Seed the SIC→sector map as a static lookup.

2. **`filings` — period + provenance.** Add `period_of_report` (the fiscal
   period the document covers, distinct from `filed_at`), `accession_number`,
   and `source_type` (default `'sec_filing'`; later phases add `'xbrl'`,
   `'price'`, etc.). Widen the `form_type` `'10-K'|'10-Q'` constraint so 8-K /
   DEF 14A can land in later phases. Keep `url` unique (idempotent ingest).

3. **Point-in-time integrity.** Standardize on two timestamps everywhere a fact
   originates: `period_of_report` (what period it describes) and `filed_at`
   (when it became public). This is the single most important change for a
   long-term tool — it makes "what was knowable as of date X" answerable and
   keeps future backtests honest. Document the rule: no analysis may use a row
   whose `filed_at` is after the as-of date.

4. **Indexes.** Add btree indexes on the hot join paths
   (`filings(company_id, period_of_report)`, `chunks(filing_id)`). Confirm the
   existing HNSW index on `chunks.embedding` (`vector_cosine_ops`) is present
   and used.

5. **Backfill.** One-off script to populate `period_of_report`,
   `accession_number`, and `sector`/`industry` for already-ingested filings
   from the EDGAR submissions JSON. Re-running must be idempotent.

## Definition of done

For a previously ingested company, every filing has a `period_of_report` and
`accession_number`, carries a `sector`, and an "as of date D" query provably
excludes filings with `filed_at > D`.
