# Phase 13 — Monitoring + evals

**Status: planned.** Lands last because it runs in the Phase 5 worker and
summarizes change using every structured signal built in Phases 8–12. This is
the original Phase 8, expanded now that there are real signals to monitor and
score.

**Outcome:** proactive (new filings detected and explained) and measurable
(answers and valuations scored, not eyeballed).

## Build

1. **`compare_filings(company, year1, year2, section)` tool.** Retrieve the same
   section from two periods (via Phase 7's `get_filing`) and diff/summarize what
   changed — added risk factors, shifted MD&A language. Pair textual diffs with
   structured deltas from `financial_facts` ("risk language on supply chain
   added AND gross margin fell 3pts").

2. **Scheduled ingestion (arq cron in the Phase 5 worker).** Poll EDGAR for new
   filings on tracked companies, ingest them, run the extraction passes
   (Phase 12) and `compare_filings` vs. the prior period, and emit a
   "what changed" summary — new material events, management changes, product
   stage transitions, insider clusters, valuation moves. Pull becomes push.

3. **Eval harness (`evals/`).** Run a test set through `/ask` and score:
   keyword/citation presence to start, LLM-as-judge later. Include multi-tool,
   valuation, and coverage-guidance cases. Add valuation-specific checks (fair
   value within a sane band of a hand-computed reference).

4. **Cost evals.** Join the per-request token telemetry (logged since Phase 3)
   to the scorecard — track tokens-per-answered-question alongside quality so a
   caching or redundant-search regression is caught like any quality regression.

## Definition of done

A new filing is detected automatically and summarized with both textual and
numeric changes; the eval script produces a quality score, a valuation-accuracy
check, and a cost-per-question figure over the test set.
