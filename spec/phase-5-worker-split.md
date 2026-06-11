# Phase 5 — Worker split + agent-triggered ingest + conversation persistence

**Status: planned.** The right-sized microservice move: API and background
worker as separate containers sharing Postgres. Don't split further yet — no
service mesh, no DB-per-service, no gRPC.

**Outcome:** ingestion runs in the background, the chat can fetch missing
filings itself ("I don't have NVDA's 2023 10-K — want me to get it?" → does
it), and conversations survive across turns and client restarts.

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
   task; the REST endpoint now just enqueues and returns a job id. New
   `ingest_jobs` table (or arq's own job state) for status: queued / running /
   done / failed, with error detail.
3. **Agent tools** in `tools/registry.py`:
   - `ingest_filing(ticker, form_type, fiscal_year)` — validate, enqueue,
     return job id.
   - `check_ingest_status(job_id)` — so the model can report progress.
4. **Conversation persistence.** The phase-4 stateless `messages` array stops
   being enough here: an ingest job finishes minutes after the turn that
   started it, so something server-side must remember "this conversation is
   waiting on job X" for the next turn to pick up. Build:
   - `conversations` and `messages` tables in Postgres; `/ask` takes a
     `conversation_id`;
   - store *references* in messages (chunk ids, job ids), not raw tool-result
     blobs — rebuild context selectively per turn, applying the phase-4
     compaction rules;
   - link pending ingest jobs to their conversation so a later turn can answer
     the original question once ingestion completes.
5. **docker-compose:** grows to `db`, `redis`, `api`, `worker` — same codebase,
   two entrypoints (`uvicorn app.main:app` and the arq worker).
6. Idempotency still holds: re-ingesting an existing filing is a no-op thanks to
   the unique constraint.

## Definition of done

From chat: ask about a missing filing → the agent offers to ingest → user says
yes → job is enqueued and runs in the worker → a later turn (same
`conversation_id`, after a client restart) confirms completion and answers the
original question with citations. `docker compose up` brings up all four
services.
