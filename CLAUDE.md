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
- **Generation:** Anthropic Claude (model in `settings.chat_model`)
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
  models.py        SQLAlchemy models (filings, chunks, companies)
  schemas.py       Pydantic request/response
  main.py          FastAPI app + /health
  ingest/          edgar.py (SEC client), chunk.py (splitting), embed.py (OpenAI)
  rag/             retrieve.py (vector search), generate.py (Claude answers)
  tools/           registry.py (tool-calling defs + dispatch)   [Phase 2+]
  market/          prices.py (market data client)               [Phase 3]
  routers/         documents.py (ingest endpoints), ask.py (query endpoint)
evals/             test_set.example.json + scoring (Phase 4)
scripts/           init_db.sql (enables pgvector)
```

## Build order (do these in sequence — see SPEC.md for detail)

- **Phase 1 — Plain RAG.** Ingest a company's filings -> chunk -> embed -> store.
  `POST /ask` does a fixed embed -> retrieve -> prompt -> answer with citations.
  Goal: one company, end to end, working and demoable.
- **Phase 2 — Tool-calling.** Replace the hardcoded retrieval in `/ask` with a
  `search_filings` tool the model invokes. Build the real loop: send tools ->
  model requests one -> validate args -> run handler -> return result -> repeat.
- **Phase 3 — Actions + structured data.** Add `compare_filings` (year-over-year
  diff) and `get_stock_price`. This is where filing text meets real numbers.
- **Phase 4 — Monitoring + evals.** Scheduled ingestion that detects new filings
  and reports changes; an eval harness scoring answers against `evals/`.

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
