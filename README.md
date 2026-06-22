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

### 1. Setup

```bash
# Clone and create a Python virtual environment
python3 -m venv .venv && source .venv/bin/activate
pip3 install -r requirements.txt

# Copy the example env file and fill in your values
cp .env.example .env
```

Open `.env` and set the following:

| Variable | What it is |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key (generation) |
| `OPENAI_API_KEY` | OpenAI API key (embeddings only) |
| `DATABASE_URL` | PostgreSQL connection string (must have pgvector enabled) |
| `REDIS_URL` | Redis connection string (default: `redis://localhost:6379`) |
| `SEC_USER_AGENT` | A descriptive string, e.g. `"Your Name your@email.com"` |
| `API_KEY` | Secret key for script/CLI access (`X-API-Key` header). Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `LOGIN_PASSWORD` | Password for the browser login screen (`POST /auth/login`) |
| `JWT_SECRET` | Signs session cookies. Generate the same way as `API_KEY` |
| `ALLOWED_ORIGINS` | Comma-separated frontend origins, e.g. `https://my-app.vercel.app,http://localhost:3000` |

You also need to enable the `pgvector` extension on your database. Run once:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 2. Running locally

This app runs as **three separate processes** — start each in its own terminal:

**Terminal 1 — Redis** (the job queue between the API and worker):
```bash
# Homebrew
brew services start redis

# or Docker
docker run -d -p 6379:6379 redis:alpine
```

**Terminal 2 — API:**
```bash
source .venv/bin/activate
uvicorn app.main:app --reload
# → http://localhost:8000/health
```

**Terminal 3 — Ingest worker:**
```bash
source .venv/bin/activate
arq app.worker.WorkerSettings
```

Once all three are running, `POST /ask` with a `question` (and optionally a `conversation_id`) to start querying filings. The worker handles all ingestion in the background — the API and worker communicate through Redis.

### 3. Deployment recommendations

The service has two processes (API + worker) sharing one codebase, so you build a single Docker image and run it twice with different start commands.

**Recommended: Railway**
- Works well if you already have an external Postgres (e.g. Supabase) — just point `DATABASE_URL` at it.
- Add the built-in Redis plugin (free 25 MB tier is enough for a job queue).
- Create two services from the same GitHub repo, override the start command per service:
  - API: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
  - Worker: `arq app.worker.WorkerSettings`
- Set `DATABASE_URL`, `REDIS_URL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `SEC_USER_AGENT` as environment variables on both services.

**Supabase note:** use the direct connection string (port 5432) for the worker — arq holds long-lived connections that don't play well with the connection pooler (port 6543).

## How it works

See `docs/how-it-works.md` for the full description.

## Roadmap

See `SPEC.md` for the full phased build plan. In short:

- **Phase 1** ✅ Plain RAG over one company's filings.
- **Phase 2** ✅ Tool-calling: the model decides when to retrieve.
- **Phase 3** ✅ Token efficiency: prompt caching, chunk dedup, HyDE on Haiku, usage logging.
- **Phase 4** ✅ Conversational guidance: persistent conversations, simplified API, token telemetry.
- **Phase 5** ✅ Worker split: arq background worker, ingest via agent tools, job tracking.
- **Phase 6** ✅ Schema hardening: `period_of_report`, `accession_number`, `sector/industry` on companies; point-in-time contract.
- **Phase 7** ✅ Section-aware ingestion: 3-pass chunker, `item_number`/`heading` on chunks, `get_filing` tool.
- **Phase 8** ✅ Structured financials (XBRL): `financial_facts` table, `get_financials` tool — numeric queries bypass vector search.
- **Phase 9** — Prices + macro: Stooq EOD prices, FRED macro series, `get_price`/`get_macro` tools.
- **Phase 10** — Valuation engine: DCF, reverse-DCF, multiples, Graham number, `run_valuation` tool.
- **Phase 11** — Sector context: peer comparison, sector-median multiples.
- **Phase 12** — Qualitative event extraction: management changes, product pipeline, insider activity.
- **Phase 13** — Monitoring + evals: auto-detect new filings, `compare_filings` tool, eval harness.

## Project files

- `CLAUDE.md` — context for Claude Code (read this if you're building with it).
- `SPEC.md` — detailed architecture and phase-by-phase plan.
- `app/` — the service (see `CLAUDE.md` for the layout).

## Notes

This is a learning-grade project, not investment advice. Generated answers can be
wrong; always verify against the primary filing. SEC EDGAR data is public; respect
their fair-access rules (~10 requests/second, descriptive User-Agent).
