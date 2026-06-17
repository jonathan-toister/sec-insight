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
   - `list_filings(ticker?)` — query Postgres for what's already ingested **and
     what is currently in-flight**. Returns ticker, form type, fiscal year,
     ingested_at, and a status (`ingested` / `ingesting` / `failed`) drawn from
     `ingest_jobs`. The agent uses this to answer "what do you have?", to detect
     gaps before searching, and to recognize a filing that is mid-ingest rather
     than missing.
   - `list_companies()` — return all companies for which we have any filings.
   - `ingest_filing(ticker, form_type, fiscal_year)` — validate, enqueue an
     arq job, return job id. Triggered when the agent detects a gap or the user
     explicitly requests it ("please ingest NVDA's 2023 10-K").
   - `check_ingest_status(job_id, wait?)` — read job state from Redis/Postgres
     so the agent can report progress across turns. Supports an optional
     server-side **blocking wait**: when `wait` is set, the tool polls
     internally up to a timeout and returns once the job reaches a terminal
     state (done/failed). This lets the agent answer within the same `/ask`
     turn without spending a tool-call round-trip per poll. Without `wait` it
     returns the current state immediately.
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

## Agent wait-policy (no-UI consideration)

The async worker is required because ingesting a 10-K takes minutes — that
latency is inherent to the work (fetch → chunk → embed thousands of chunks →
upsert), not a product of the architecture. Making ingest synchronous wouldn't
make it faster; it would just hang an HTTP request.

But there is currently **no UI** — the only client is `POST /ask` and a
server-side agent loop. So "ack now, answer on a later turn" would force the
*caller* to make a second `/ask` call to get the answer, which is exactly the
friction we want to avoid. Because the agent's tool-calling loop runs
server-side within a single request, the agent can instead enqueue the job and
block on `check_ingest_status(wait=…)` until it completes, then search and
answer — all in one response, no second call needed.

**Dependent-question intent.** The discriminator is whether the triggering
message contains a question that *depends on* the doc being ingested. The agent
infers this from the message itself:

- **Dependent question present, single filing** ("ingest NVDA's 2023 10-K and
  tell me their R&D spend") → enqueue, block-and-wait on
  `check_ingest_status(wait)`, then answer in the same turn.
- **Dependent question present, but the wait is non-trivial** (bulk, or the
  agent expects minutes) → don't silently block. Offer the choice: "this'll
  take ~2 min — want me to wait and answer now, or ingest in the background so
  you're not blocked?" Block or ack based on the reply.
- **No dependent question** ("ingest NVDA's 2023 10-K") → just ingest. There is
  nothing to wait for, so do **not** ask whether they have a question; confirm
  when done (or ack and let them ask whenever).
- **Bulk / non-blocking ("ingest these 20 filings")** → enqueue all,
  acknowledge, and let the user re-check later. Do not block the turn.

**Querying a filing that is still ingesting.** If a question targets a filing
that has an in-flight job (a `search_filings` miss + an `ingesting` row from
`list_filings`), the agent must not answer "I don't have that" or hallucinate.
It responds conversationally that the filing is still being ingested (with
rough elapsed time if available) and offers to wait and answer now
(`check_ingest_status(wait)`) or to be re-asked once it's ready. The
`conversation_id` link lets it tie the in-flight job back to the user.

Caveats to revisit (not solved now):

- Blocking a request for minutes can trip HTTP/proxy timeouts. Acceptable for a
  backend/dev setup; revisit when a real client or streaming surface exists.
- The blocking wait needs a sane internal timeout so a stuck job degrades to a
  "still running, check back" response rather than hanging indefinitely.

This is a behavior/prompt decision plus the optional `wait` flag on
`check_ingest_status` — no new component, table, or endpoint.

## Definition of done

1. **Coverage tools work.** Asking "what companies do you have?" or "what NVDA
   filings do you have?" triggers `list_companies` / `list_filings` and returns
   accurate results from Postgres.
2. **Explicit user-requested ingest works.** "Ingest Apple's 2023 10-K and tell
   me X" → agent calls `ingest_filing` → blocks on `check_ingest_status(wait)`
   → job runs in the worker → agent answers X with citations **in the same
   turn**. A bulk ingest request instead acks without blocking.
3. **Agent-detected gap ingest works.** Ask about a missing filing → agent
   calls `list_filings`, detects the gap, offers to ingest → user says yes →
   agent calls `ingest_filing` → a later turn calls `check_ingest_status`,
   confirms completion, and answers the original question with citations.
4. **Mid-ingest query is handled gracefully.** Asking about a filing whose
   ingest job is still running returns a conversational "still being ingested,
   not available yet" response (via `list_filings` surfacing the `ingesting`
   status) — never an empty/hallucinated answer — and offers to wait or be
   re-asked.
5. Starting `api` and `worker` as separate processes brings up all components
   without error.
