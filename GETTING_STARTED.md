# Getting started with Claude Code

This file covers the Claude Code workflow for continuing development. For
project setup and running the service, see **README.md** first.

Phases 1–8 are implemented (plain RAG, tool-calling agent loop, token efficiency,
persistent conversations, async ingest worker, schema hardening, section-aware
ingestion, XBRL structured financials). The next phase to build is Phase 9.

## 1. Open it

Open the `sec-insight/` folder as its own project in VS Code (File → Open
Folder). Open the integrated terminal. Start Claude Code in that terminal. It will
read `CLAUDE.md` automatically — that's your project's standing context.

## 2. Continue with Claude Code from Phase 9

The golden rule: **one phase at a time**, and run it before moving on. `SPEC.md`
has the detailed steps; `CLAUDE.md` has the build order. Phases 1–8 are done.

Good opening prompt for Phase 9:

> "Read CLAUDE.md and spec/phase-9-prices-macro.md. Phases 1–8 are fully
> implemented. Start Phase 9: Stooq EOD prices, FRED macro series, and the
> get_price/get_macro tools. Show me the plan before coding."

The existing implementation is a useful reference:
- `app/rag/generate.py` — the agentic loop with prompt caching
- `app/tools/registry.py` — how tools are defined and dispatched (`get_financials` is the most recent addition)
- `app/ingest/xbrl.py` — pattern for fetching structured data from an external source and upserting rows
- `app/models.py` — the current DB schema (see `FinancialFact` and `MetricDimension` for the Phase 8 pattern to follow)

## 3. Tips for working with Claude Code here

- Ask it to **show a plan before writing code** on each step — cheaper to correct.
- Have it **run the thing** after each piece (ingest a company, hit `/ask`) rather
  than writing many files then debugging all at once.
- Keep `CLAUDE.md` updated as decisions change — it's the memory across sessions.
- Commit after each working step so you can roll back.
- If it tries to jump ahead a phase, redirect it — the phases build on each other.

## 4. Next milestone

To confirm the Phase 8 baseline is healthy before starting Phase 9:

1. Ask the agent to ingest a company: `"Please ingest AAPL's 2024 10-K"`
2. Once done, ask a numeric question: `"What was Apple's revenue in FY2024?"` — the agent should call `get_financials`, not `search_filings`, and return a number from the XBRL data.
3. Ask a text question: `"What were Apple's biggest risks?"` — this should use `search_filings` and return a cited answer.

That confirms Phases 1–8 are healthy before you start Phase 9.
