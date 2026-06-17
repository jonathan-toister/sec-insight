# SEC Insight

A backend service for asking natural-language questions about SEC filings
(10-K / 10-Q) and getting answers grounded in the actual documents, with
citations. Built as a RAG system that grows into a tool-using agent.

It deliberately does what consumer "chat with your docs" tools cannot: it pulls
filings live from SEC EDGAR, joins filing text with real market numbers, takes
actions through tool-calling, and can monitor for new filings and report what
changed.

## Stack

Python · FastAPI · PostgreSQL + pgvector · SQLAlchemy · Anthropic Claude
(generation) · OpenAI embeddings · SEC EDGAR (data).

## Quick start

```bash
# 1. Python env
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Config
cp .env.example .env   # fill in ANTHROPIC_API_KEY, OPENAI_API_KEY,
                       # DATABASE_URL, REDIS_URL,
                       # SEC_USER_AGENT ("Your Name your@email")

# 3. Start Redis (needed for the background ingest worker)
redis-server --daemonize yes   # or: docker run -d -p 6379:6379 redis

# 4. Start the API
uvicorn app.main:app --reload  # http://localhost:8000/health

# 5. Start the ingest worker (separate terminal — same codebase, different process)
arq app.worker.WorkerSettings
```

You need two API keys: **Anthropic** (generation) and **OpenAI** (embeddings
only). SEC EDGAR needs no key, just a descriptive `User-Agent`.

## How it works (Phases 1–4 implemented)

1. **Ingest** — `POST /companies/{ticker}/ingest` pulls a company's recent
   filings from EDGAR, splits them into chunks, embeds each chunk with OpenAI
   (via HyDE for better retrieval alignment), and stores text + vector in Postgres.
2. **Ask** — `POST /ask` runs an agentic loop: Claude calls `search_filings`
   one or more times (with HyDE + pgvector retrieval), then calls `format_answer`
   with a cited plain-English answer. Pass `conversation_id` to continue a prior
   conversation; omit to start a new one.

Conversations and per-message token telemetry are persisted to Postgres.

## Roadmap

See `SPEC.md` for the full phased build plan. In short:

- **Phase 1** ✅ Plain RAG over one company's filings.
- **Phase 2** ✅ Tool-calling: the model decides when to retrieve.
- **Phase 3** ✅ Token efficiency: prompt caching, chunk dedup, HyDE on Haiku, usage logging.
- **Phase 4** ✅ Conversational guidance: persistent conversations, simplified API, token telemetry.
- **Phase 5** — Worker split + coverage tools + ingest job tracking.
- **Phase 6** — Action tools: year-over-year diffs + live stock prices.
- **Phase 7** — New data sources (earnings calls, press releases).
- **Phase 8** — Monitoring for new filings + an eval harness.

## Project files

- `CLAUDE.md` — context for Claude Code (read this if you're building with it).
- `SPEC.md` — detailed architecture and phase-by-phase plan.
- `app/` — the service (see `CLAUDE.md` for the layout).

## Notes

This is a learning-grade project, not investment advice. Generated answers can be
wrong; always verify against the primary filing. SEC EDGAR data is public; respect
their fair-access rules (~10 requests/second, descriptive User-Agent).
