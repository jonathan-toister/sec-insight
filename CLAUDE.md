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
  config.py        settings from .env
  db.py            engine/session, pgvector setup
  models.py        SQLAlchemy models (companies, filings, chunks, conversations, messages)
  schemas.py       Pydantic request/response
  main.py          FastAPI app + /health
  ingest/          edgar.py (SEC client), chunk.py (splitting), embed.py (OpenAI)
  rag/             retrieve.py (vector search), generate.py (Claude agent loop),
                   hyde.py (HyDE query expansion with Haiku)
  tools/           registry.py (tool-calling defs + dispatch)
  market/          prices.py (market data client stub)          [Phase 6]
  routers/         documents.py (ingest endpoints), ask.py (query endpoint)
evals/             test_set.example.json + scoring              [Phase 8]
scripts/           init_db.sql (enables pgvector)
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
- **Phase 5 — Worker split** Async ingest worker, ingest job tracking, coverage
  tools (list_companies, list_filings) in the agent.
- **Phase 6 — Actions + structured data.** Add `compare_filings` and
  `get_stock_price`. Filing text meets real numbers.
- **Phase 7 — New data sources.** Earnings call transcripts, press releases.
- **Phase 8 — Monitoring + evals.** Scheduled ingestion, eval harness.

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
