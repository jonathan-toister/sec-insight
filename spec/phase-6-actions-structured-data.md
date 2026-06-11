# Phase 6 — Actions + structured data

**Status: planned.** This is the original SPEC's Phase 3, unchanged in content,
renumbered. It lands after the worker split because the phase-5 agent loop makes
these tools immediately useful in conversation.

**Outcome:** filing text meets real numbers; the agent does things, not just reads.

## Build

1. `tools/registry.py` — add:
   - `get_filing(company, year, form_type)` — fetch a specific document.
   - `compare_filings(company, year1, year2, section)` — retrieve the same section
     from two years and diff/summarize what changed (e.g. risk factors added).
   - `get_stock_price(ticker)` — via `market/prices.py`.
2. `market/prices.py` — wrap a price API (Alpha Vantage / Finnhub, or `yfinance`
   for a no-key start).

Now the agent can answer "how did this company's risk factors change, and where's
the stock now?" by orchestrating multiple tools. **This is the NotebookLM-can't-do
moment** — structured + unstructured, combined, with actions.

## Definition of done

A single question provably triggers two tools and the answer combines both
results.
