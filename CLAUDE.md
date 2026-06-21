# CLAUDE.md — Project context for Claude Code

This file is read automatically by Claude Code. It defines what we're building,
the conventions to follow, and the order to build in. Keep it up to date as the
project grows.

## What this is

**SEC Insight** — a backend service that lets an investor ask natural-language
questions about SEC filings (10-K / 10-Q) and get answers grounded in the actual
documents, with citations. It is a RAG system that grows into a tool-using agent.

It is explicitly NOT a "chat over uploaded docs" toy. The whole point is to do
things a consumer tool (NotebookLM, ChatGPT file upload) structurally cannot:

1. **Automated ingestion** of live filings straight from SEC EDGAR (not manual upload).
2. **Structured-data joins** — filing text alongside real numbers (prices, fundamentals).
3. **Actions via tool-calling** — diffing filings, fetching prices, not just answering.
4. **Proactive monitoring** — detect new filings and report what changed.

When making design choices, prefer the option that moves toward those four
differentiators over the option that just makes a nicer chatbot.

## Stack

- **Language:** Python 3.11+
- **API:** FastAPI (run: `uvicorn app.main:app --reload`)
- **Worker:** arq (run: `arq app.worker.WorkerSettings`) — separate process, same codebase
- **Queue:** Redis (job handoff between API and worker; set `REDIS_URL` in `.env`)
- **DB:** PostgreSQL + pgvector (external; set `DATABASE_URL` in `.env`)
- **ORM:** SQLAlchemy 2.x, `psycopg` (v3) driver
- **Generation:** Anthropic Claude (`settings.chat_model` for main answers, `settings.hyde_model` for HyDE)
- **Embeddings:** OpenAI `text-embedding-3-small` (1536 dims) — embeddings ONLY
- **Data source:** SEC EDGAR free JSON/HTML endpoints (no key; needs User-Agent)
- **Config:** pydantic-settings reading `.env` (see `app/config.py`, `.env.example`)

Anthropic has no embeddings API, so OpenAI is used purely for embeddings and
Claude purely for generation. Don't mix these up.

## Layout

```
app/
  config.py        settings from .env (incl. REDIS_URL)
  db.py            engine/session, pgvector setup, create_redis_pool()
  models.py        SQLAlchemy models (companies, filings, chunks, conversations,
                   messages, ingest_jobs)
                   [Phase 6] + period_of_report/accession_number on filings,
                             + sector/industry on companies
                   [Phase 7] + item_number/heading/is_table/fiscal_year on chunks
                   [Phase 8] + financial_facts, metric_dimensions tables
                   [Phase 9] + prices, macro_series tables
                   [Phase 10] + valuation_models, valuations tables
                   [Phase 11] + sector_profiles, company_peers tables
                   [Phase 12] + management_changes, product_events,
                               insider_transactions tables
  schemas.py       Pydantic request/response
  main.py          FastAPI app + /health; lifespan creates arq Redis pool
  worker.py        arq WorkerSettings + ingest_filing_task (worker entrypoint)
  ingest/          edgar.py (SEC client), chunk.py (splitting), embed.py (OpenAI),
                   pipeline.py (upsert_company + ingest_one_filing — shared by worker)
                   [Phase 7] edgar.py extracts section_map from HTML before stripping;
                             chunk.py uses 3-pass split: section → paragraph → sentence
                   [Phase 8] xbrl.py (fetch + upsert XBRL company facts)
  rag/             retrieve.py (vector search), generate.py (Claude agent loop),
                   hyde.py (HyDE query expansion with Haiku)
                   [Phase 10] valuation.py (DCF, reverse-DCF, multiples, DDM, Graham)
  tools/           registry.py (5 tool schemas + dispatch: search_filings,
                   list_companies, list_filings, ingest_filing, check_ingest_status)
                   [Phase 7]  + get_filing; search_filings gains item_number/fiscal_year filters
                   [Phase 8]  + get_financials
                   [Phase 9]  + get_price, get_macro
                   [Phase 10] + run_valuation, analyze_company
                   [Phase 11] + get_sector_context
                   [Phase 12] + get_management_changes, get_product_pipeline,
                               get_insider_activity
                   [Phase 13] + compare_filings
  market/          [Phase 9] prices.py (Stooq EOD client), macro.py (FRED client)
  auth/            dependencies.py (verify_api_key — shared FastAPI dep),
                   session.py (JWT create/verify for httpOnly cookies)
  routers/         documents.py (GET /filings), ask.py (POST /ask),
                   auth.py (POST /auth/login, POST /auth/logout)
evals/             [Phase 13] test_set.json + eval harness + cost scorecard
scripts/           init_db.sql (enables pgvector)
                   [Phase 6] backfill_phase6.py (period_of_report, accession_number,
                             sector from EDGAR submissions JSON)
                   [Phase 7] backfill_phase7.py (truncate chunks+filings, re-ingest
                             all filings with new chunker)
```

## Build order (see `spec/` for detail — one file per phase)

- **Phase 1 — Plain RAG** ✅ Ingest filings → chunk → embed → store. `POST /ask`
  does embed → retrieve → prompt → answer with citations.
- **Phase 2 — Tool-calling** ✅ Replaced hardcoded retrieval with a `search_filings`
  tool the model invokes in a loop. Claude decides when and what to search.
- **Phase 3 — Token efficiency** ✅ Prompt caching (system prompt + tool schemas +
  last message), chunk dedup across multi-search turns, HyDE routed to Haiku,
  per-request token usage logged.
- **Phase 4 — Conversational guidance** ✅ Simplified `/ask` API (question +
  conversation_id only), server-side conversation persistence, token telemetry per
  message stored in DB.
- **Phase 5 — Worker split** ✅ Ingest moves to an arq background worker. REST
  ingest endpoint removed — all ingest goes through the agent (`ingest_filing`,
  `check_ingest_status`, `list_companies`, `list_filings` tools). `ingest_jobs`
  table tracks status. Two processes: `uvicorn app.main:app` (API) and
  `arq app.worker.WorkerSettings` (worker).
- **Phase 6 + 7 — Schema hardening + section-aware ingestion** *(implement as one sprint).*
  Phase 6: add `period_of_report`/`accession_number`/`source_type` to filings,
  `sector`/`industry`/`fiscal_year_end` to companies; establish point-in-time
  contract. Phase 7: fix section detection by extracting a `section_map` from HTML
  structure before stripping; upgrade chunker to three-pass pipeline (section →
  paragraph → sentence-boundary alignment); add `item_number`/`heading`/`is_table`/
  `fiscal_year` to chunks; extend `search_filings` with section + fiscal_year
  filters; add `get_filing` tool; re-ingest all existing filings from scratch.
- **Phase 8 — Structured financials (XBRL).** Fetch XBRL company facts from EDGAR;
  store canonical metrics in `financial_facts` (SQL rows, not embeddings); add
  `get_financials` tool. Revenue, EPS, FCF components queryable directly.
- **Phase 9 — Prices + macro.** Stooq for EOD prices; FRED for risk-free rate and
  macro series. `prices` and `macro_series` tables with point-in-time semantics.
  `get_price` and `get_macro` tools.
- **Phase 10 — Valuation engine.** DCF, reverse-DCF, relative multiples, DDM,
  Graham number, quality screens — each as a small testable function in
  `rag/valuation.py`. `run_valuation(ticker)` tool returns all sector-appropriate
  model outputs. `analyze_company(ticker, focus=[])` compound tool batches
  financials + prices + valuation + sector context into one call (keeps
  investment-analysis turns to ~3–4 instead of 8+). `"investment_analysis"`
  response type added to `format_answer` (summary / valuation / risk / verdict).
- **Phase 11 — Sector context.** `sector_profiles` (typical multiples, key metrics,
  preferred models per sector) and `company_peers` tables. `get_sector_context`
  tool frames every multiple against sector median + company's 5-yr history.
- **Phase 12 — Qualitative event extraction.** After Phase 7 section tagging, run
  targeted LLM extraction on relevant sections. `management_changes`,
  `product_events`, `insider_transactions` tables — each row cites its source
  chunk. `get_management_changes`, `get_product_pipeline`, `get_insider_activity`
  tools surface patterns, not raw events.
- **Phase 13 — Monitoring + evals.** `compare_filings` tool diffs sections across
  periods (text + structured deltas). arq cron detects new filings, auto-ingests,
  runs Phase 12 extraction, emits "what changed" summary. Eval harness scores
  answers and valuation accuracy; cost scorecard joins token telemetry to quality.

Do not jump ahead. Each phase should run before the next begins.

## Conventions

- Keep secrets in `.env` (gitignored). Never hardcode keys. Read via `settings`.
- All SEC requests must send `settings.sec_user_agent` and respect ~10 req/sec.
- Embeddings: the SAME function embeds documents at ingest and questions at query
  time — keep it in one place (`app/ingest/embed.py`).
- Citations are mandatory in answers — every claim ties back to a filing. In this
  domain an ungrounded answer is worthless.
- Validate tool arguments before executing — the model can return bad/hallucinated
  args. Handle that gracefully; never trust them blindly.
- Type hints everywhere; prefer small, testable functions.

## Definition of done per phase

A phase is done when it runs against at least one real company and its core
endpoint returns correct, cited output. Phase 4 adds: answers are scored, not
just eyeballed.
