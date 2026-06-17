# Phase 5 — Worker split + agent-triggered ingest

**Status: planned.** The right-sized microservice move: API and background
worker as separate processes sharing Postgres. Don't split further yet — no
service mesh, no DB-per-service, no gRPC.

**Outcome:** ingestion runs in the background exclusively through the agent.
The user asks a question or explicitly asks to ingest a filing — the agent
handles it, tracks progress, and follows up. Users can also ask the agent
what filings are already available.

## Why this split (and only this one)

Ingestion is the one component with genuinely different characteristics:
bursty, long-running (minutes), rate-limited against EDGAR, and — in phase 8 —
scheduled. It cannot run inline in a chat request. Everything else stays in the
API process; module boundaries inside `app/` (each package exposing an explicit
service interface, owning its own tables) give the rest of the microservices
benefit at none of the cost.

## Build

1. **Queue:** Redis + `arq` (async-native, fits FastAPI; lighter than Celery).
2. **Worker:** move the ingest logic out of `routers/documents.py` into an arq
   task. New `ingest_jobs` table for status: queued / running / done / failed,
   with error detail. The worker is the only process that touches EDGAR.
3. **Agent tools** in `tools/registry.py` — all ingest operations go through
   the agent, never via a direct REST endpoint:
   - `list_filings(ticker?)` — query Postgres for what's already ingested.
     Returns ticker, form type, fiscal year, ingested_at. The agent uses this
     to answer "what do you have?" and to detect gaps before searching.
   - `list_companies()` — return all companies for which we have any filings.
   - `ingest_filing(ticker, form_type, fiscal_year)` — validate, enqueue an
     arq job, return job id. Triggered when the agent detects a gap or the user
     explicitly requests it ("please ingest NVDA's 2023 10-K").
   - `check_ingest_status(job_id)` — read job state from Redis/Postgres so the
     agent can report progress across turns.
   - Link each ingest job to its `conversation_id` (persisted from phase 4) so
     a later turn can answer the original question once ingestion completes.
4. **Deployment:** `api` and `worker` as separate processes — same codebase,
   two entrypoints (`uvicorn app.main:app` and the arq worker).
5. Idempotency still holds: re-ingesting an existing filing is a no-op thanks to
   the unique constraint. `ingest_filing` for an already-ingested filing returns
   the existing record without queuing duplicate work.

## How the API and worker fit together

Both processes run from the **same codebase** and share the same Postgres
database. Redis is the handoff point: the API writes a job; the worker reads it.
All user interaction — including triggering ingest — goes through `POST /ask`.

```
                        ┌──────────────────────────────────────────┐
  User / Client         │              API Process                  │
  ──────────────        │          (uvicorn app.main:app)           │
                        │                                           │
  POST /ask  ──────────►│  ask router                               │
   "what filings        │    └─ Claude agent loop                   │
    do you have?"       │         └─ tool: list_companies ◄─────────┼─── Postgres
   "ingest NVDA 10-K"   │         └─ tool: list_filings  ◄─────────┼─── Postgres
   "what's Apple's      │         └─ tool: ingest_filing ───────────┼──► enqueue
    revenue?"           │         └─ tool: check_status  ◄──────────┼─── Redis
                        │                                           │
                        └───────────────────────────────────────────┘
                                              │  ▲
                                         push │  │ poll / read
                                              ▼  │
                        ┌──────────────────────────────────────────┐
                        │                  Redis                    │
                        │             (arq job queue)               │
                        │                                           │
                        │    job_id → { status, result, error }     │
                        └──────────────────────────────────────────┘
                                              │
                                         pop  │
                                              ▼
                        ┌──────────────────────────────────────────┐
                        │             Worker Process                │
                        │           (arq WorkerSettings)           │
                        │                                           │
                        │  ingest_filing task                       │
                        │    1. fetch filing from EDGAR             │
                        │    2. chunk text                          │
                        │    3. embed chunks (OpenAI)               │
                        │    4. upsert → Postgres/pgvector          │
                        │    5. write final status → Redis          │
                        └──────────────────────────────────────────┘
                                              │
                                        upsert│
                                              ▼
                        ┌──────────────────────────────────────────┐
                        │          Postgres + pgvector              │
                        │                                           │
                        │  companies · filings · chunks             │
                        │  conversations · messages                 │
                        │  ingest_jobs (status tracking)            │
                        └──────────────────────────────────────────┘
```

### Key points

- **One codebase, two entrypoints.** `uvicorn app.main:app` starts the API;
  `arq app.worker.WorkerSettings` starts the worker. No code duplication.
- **Agent is the single entry point for all ingest.** There is no `POST /ingest`
  REST endpoint. The only way to trigger ingestion is through the agent's
  `ingest_filing` tool, keeping the system's interface surface minimal and
  all data operations auditable via conversation history.
- **Redis is ephemeral state only.** Job status is mirrored to `ingest_jobs` in
  Postgres so it survives a Redis restart and is queryable with SQL.
- **Coverage is queryable through the agent.** `list_companies` and
  `list_filings` let Claude answer "what do you have on Apple?" before
  deciding whether to search existing chunks or offer to ingest.
- **Conversation continuity.** Each ingest job is linked to the
  `conversation_id` that triggered it. Once the worker finishes, the next turn
  in that conversation can immediately answer the original question with
  citations.
- **Rate-limiting lives in the worker.** EDGAR's ~10 req/sec limit is enforced
  there, not in the API, so it never blocks a chat response.

## Definition of done

1. **Coverage tools work.** Asking "what companies do you have?" or "what NVDA
   filings do you have?" triggers `list_companies` / `list_filings` and returns
   accurate results from Postgres.
2. **Explicit user-requested ingest works.** "Please ingest Apple's 2023 10-K"
   → agent calls `ingest_filing` → job runs in the worker → agent confirms
   completion in a follow-up turn.
3. **Agent-detected gap ingest works.** Ask about a missing filing → agent
   calls `list_filings`, detects the gap, offers to ingest → user says yes →
   agent calls `ingest_filing` → a later turn calls `check_ingest_status`,
   confirms completion, and answers the original question with citations.
4. Starting `api` and `worker` as separate processes brings up all components
   without error.
