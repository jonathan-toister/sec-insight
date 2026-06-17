# How SEC Insight Works — Phases 2–5: The Agent Loop + Ingest Worker

This document explains how the `/ask` endpoint works after Phases 2–4. No finance or ML background needed.

---

## The Big Picture

Think of SEC Insight like a **research assistant**. You ask a question. The assistant decides whether it needs to look something up, goes to find the relevant filing excerpts, reads them, and writes you an answer with citations.

Phase 2 makes this real: instead of always running a fixed lookup whether it's needed or not, Claude now *chooses* when to search — and loops until it has enough information to answer.

---

## Phase 1 vs Phase 2 — What Changed

**Phase 1** ran a fixed pipeline every single time, no matter what you asked:

```
Your question
    → Generate a hypothetical document (HyDE)
    → Embed it
    → Retrieve chunks
    → Generate answer
```

This worked, but had problems:
- Ran the full pipeline even for "thanks!" (wasted tokens and time)
- Could only search once, with one query
- No way to ask follow-up searches mid-answer

**Phase 2** replaces the fixed pipeline with a loop. Claude is now in charge:

```
Your question
    → Claude thinks: "Do I need to search? What for?"
    → Loops: search → read results → search again if needed
    → Claude writes the answer when it has enough
```

**Phase 3** made the loop cheaper: the system prompt and tool schemas are cached
with Anthropic's prompt caching API (charged at ~10% after the first call), chunks
are deduplicated across multiple searches so the same text is never resent, and
HyDE hypothetical-document generation runs on the fast/cheap Haiku model. Token
usage is logged per request.

**Phase 4** added persistent conversations and simplified the request: you now
just send a `question` (and optionally a `conversation_id` to continue a prior
conversation). Prior turns are loaded from Postgres and fed as history into the
agent loop so follow-up questions have context.

---

## The Three Response Paths

Every question ends up in one of three paths:

```
                        ┌─────────────────────────────────┐
                        │       POST /ask  {question}      │
                        └─────────────────────────────────┘
                                         │
                                         ▼
                            ┌─────────────────────┐
                            │  Claude reads the   │
                            │  question and thinks │
                            └─────────────────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                     ▼
          ┌──────────────┐    ┌───────────────────┐   ┌──────────────────┐
          │  "Hey there!"│    │ "What were KO's   │   │ "What were the   │
          │  (small talk)│    │  risk factors?"   │   │  risk factors?"  │
          └──────────────┘    │  (clear company)  │   │  (no company)    │
                 │            └───────────────────┘   └──────────────────┘
                 │                     │                       │
                 ▼                     ▼                       ▼
        ┌────────────────┐  ┌──────────────────┐  ┌───────────────────────┐
        │ Friendly reply │  │ Searches filings │  │ Asks: "Which company  │
        │ No citations   │  │ Writes cited     │  │  did you mean?"       │
        │ No disclaimer  │  │ answer           │  │                       │
        └────────────────┘  └──────────────────┘  └───────────────────────┘
```

---

## The Agentic Loop — Step by Step

This is what happens inside `run_agent()` for a real SEC question:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         run_agent(question)                              │
└─────────────────────────────────────────────────────────────────────────┘

  Step 1: Build the first message
  ┌──────────────────────────────────────────────┐
  │  messages = [                                │
  │    { role: "user", content: "What were      │
  │      Coca-Cola's risk factors?" }            │
  │  ]                                           │
  └──────────────────────────────────────────────┘
                        │
                        ▼
  Step 2: Call Claude — offer it tools
  ┌────────────────────────────────────────────────────────┐
  │  Claude sees:                                          │
  │   • Your question                                      │
  │   • Available tools: [search_filings] [format_answer]  │
  └────────────────────────────────────────────────────────┘
                        │
          ┌─────────────┴──────────────┐
          ▼                            ▼
  Claude calls                Claude calls
  search_filings               format_answer
  (needs more info)            (ready to answer)
          │                            │
          ▼                            │
  Step 3: We run the search            │
  ┌──────────────────────────┐         │
  │  1. Embed the query      │         │
  │  2. Vector search in DB  │         │
  │  3. Return top-k chunks  │         │
  └──────────────────────────┘         │
          │                            │
          ▼                            │
  Step 4: Feed results back to Claude  │
  ┌──────────────────────────────────┐ │
  │  "[1] COCA COLA CO 10-K FY2025   │ │
  │   — Item 15.                     │ │
  │   Unfavorable economic conditions│ │
  │   could negatively impact...     │ │
  │                                  │ │
  │   [2] COCA COLA CO 10-K FY2025   │ │
  │   — Item 15.                     │ │
  │   Obesity concerns may reduce... │ │
  │   ..."                           │ │
  └──────────────────────────────────┘ │
          │                            │
          └──────────────┬─────────────┘
                         ▼
  Step 5: Claude calls format_answer
  ┌────────────────────────────────────────────────────────┐
  │  {                                                     │
  │    "response_type": "research",                        │
  │    "answer": "Here are Coca-Cola's main risk           │
  │              factors... [COCA COLA CO 10-K FY2025]",  │
  │    "chunk_highlights": [                               │
  │      { chunk_index: 1, highlights: ["Unfavorable..."] }│
  │      { chunk_index: 2, highlights: ["Obesity..."] }    │
  │    ]                                                   │
  │  }                                                     │
  └────────────────────────────────────────────────────────┘
                         │
                         ▼
  Step 6: Return to caller
  ┌────────────────────────────────────────────────────────┐
  │  answer        — the plain-English cited answer        │
  │  sources       — deduplicated citation list            │
  │  highlights_map — which passages were most relevant    │
  │  all_chunks    — the raw filing excerpts               │
  └────────────────────────────────────────────────────────┘
```

> Claude can call `search_filings` multiple times before calling `format_answer`. For example, a complex question might trigger two separate searches before Claude has enough context to write the answer. The loop runs up to **10 turns** before giving up.

---

## The Tools

Claude has two tools available in Phase 2:

### `search_filings` — find information in indexed filings

Claude calls this when it needs to look something up.

| Argument | Required? | What it is |
|---|---|---|
| `query` | Yes | What to search for (e.g. "revenue growth 2023") |
| `ticker` | **Yes** | Company stock symbol (e.g. "KO", "AAPL") |
| `form_type` | No | Filter to `10-K` or `10-Q` only |
| `fiscal_year` | No | Filter to a specific year (e.g. `2023`) |
| `k` | No | How many results to return (1–20, default 6) |

**Why is `ticker` required?** Without knowing the company, we'd search across all indexed filings and get irrelevant results. Claude must identify the company from your question before searching.

**What if there are no results?** The tool returns an explicit message like:
```
No indexed filings found for ticker 'XYZ' matching your query.
Try different search terms, or check whether this company has been ingested.
```
Claude reads this and tells you, rather than hallucinating an answer.

---

### `format_answer` — write and return the final answer

Claude calls this when it's ready to respond. It signals the end of the loop.

| Field | What it does |
|---|---|
| `response_type` | `"research"` for filing questions, `"conversational"` for small talk |
| `answer` | The full answer text with inline citations |
| `chunk_highlights` | Which sentences in each retrieved passage were most relevant |

The `response_type` field is how we split the two code paths:
- `"conversational"` → return immediately with no sources, no disclaimer
- `"research"` → build the full citation structure and return everything

---

## Validation: Catching Bad Tool Calls

The model can occasionally hallucinate invalid arguments. Before running any tool, we validate:

```
Claude calls search_filings with args
                 │
                 ▼
        _validate_search_args()
        ┌─────────────────────────────────────────────┐
        │  query empty?       → error back to Claude  │
        │  ticker missing?    → error back to Claude  │
        │  form_type invalid? → error back to Claude  │
        │  k out of range?    → silently clamp to 1–20│
        └─────────────────────────────────────────────┘
                 │
        valid    │    invalid
         ┌───────┴───────┐
         ▼               ▼
    run search      return error as
                    tool_result — Claude
                    reads it and adjusts
```

Validation errors don't crash the server. They're returned to Claude as a tool result (just like a search result), so Claude can try again with corrected arguments or explain the problem to the user.

---

## Where Everything Lives

```
app/
├── routers/ask.py          Entry point. Calls run_agent(), returns AskResponse.
│
├── rag/generate.py         The loop lives here.
│   ├── run_agent()         Main agentic loop — max 10 turns
│   ├── _AGENT_SYSTEM_PROMPT  Tells Claude the rules and when to use each tool
│   └── _FORMAT_TOOL        Schema for the format_answer tool
│
└── tools/registry.py       Tool definitions + handlers.
    ├── TOOL_SCHEMAS        The search_filings JSON schema Claude sees
    ├── dispatch()          Routes a tool call to the right handler
    ├── _validate_search_args()  Arg validation before any DB call
    ├── handle_search_filings()  Embeds query (via HyDE) → vector search → return chunks
    └── _format_result_chunks()  Deduplicates chunks seen in prior searches
```

---

## Full Request Lifecycle (Sequence Diagram)

```
You          /ask router      run_agent()        Claude       PostgreSQL
 │                │                │                │              │
 │  POST /ask     │                │                │              │
 │  {question,    │                │                │              │
 │   conv_id?}    │                │                │              │
 │─────────────>  │                │                │              │
 │                │ load history   │                │              │
 │                │─────────────────────────────────────────────> │
 │                │ prior messages │                │              │
 │                │<─────────────────────────────────────────────-│
 │                │  run_agent()   │                │              │
 │                │───────────────>│                │              │
 │                │                │  question +    │              │
 │                │                │  history +     │              │
 │                │                │  tool schemas  │              │
 │                │                │───────────────>│              │
 │                │                │                │              │
 │                │                │  search_filings│              │
 │                │                │  (ticker="KO") │              │
 │                │                │<───────────────│              │
 │                │                │                │              │
 │                │                │  HyDE + embed  │              │
 │                │                │─────────────────────────────> │
 │                │                │  top-k chunks  │              │
 │                │                │<─────────────────────────────-│
 │                │                │                │              │
 │                │                │  tool_result   │              │
 │                │                │  [1] KO 10-K..│              │
 │                │                │  [2] KO 10-K..│              │
 │                │                │───────────────>│              │
 │                │                │                │              │
 │                │                │  format_answer │              │
 │                │                │  (research)    │              │
 │                │                │<───────────────│              │
 │                │                │                │              │
 │                │ save messages  │                │              │
 │                │ + token usage  │                │              │
 │                │─────────────────────────────────────────────> │
 │                │  AskResponse   │                │              │
 │                │<───────────────│                │              │
 │  200 OK        │                │                │              │
 │  {answer,      │                │                │              │
 │   conv_id}     │                │                │              │
 │<───────────────│                │                │              │
```

---

## Key Design Decisions

**Why does Claude control the loop, not the code?**
Because the right number of searches depends on the question. "What are KO's risks?" needs one search. A multi-part question comparing two years might need two. A greeting needs zero. Hardcoding "always do one search" throws away that judgment.

**Why keep `format_answer` as a tool?**
It forces Claude to return structured output (highlights, response type) rather than free text. Without it, parsing citations and highlights out of a prose answer would be fragile and unreliable.

**Why is `ticker` required in `search_filings`?**
It prevents cross-company contamination and forces Claude to be explicit. If the question doesn't name a company, Claude asks the user rather than guessing — which is the right behavior for a financial tool.

**What's the max 10 turns for?**
A safety brake. Without it, a confused model could loop forever. In practice, 1–2 search calls are enough for any real question.

---

## Phase 5 — Worker Split + Ingest Tools

### Why a separate worker process?

Ingesting a 10-K takes minutes: fetch HTML from EDGAR → strip to text → split into ~500-word chunks → embed each chunk via OpenAI → write hundreds of rows to Postgres. Running that inline in a chat request would block the HTTP connection the whole time. Instead:

- The **API process** (`uvicorn`) handles all user interaction, including triggering ingest.
- The **worker process** (`arq`) executes ingest jobs in the background.
- **Redis** is the handoff: the API writes a job, the worker reads and runs it.
- **Postgres** is the source of truth for job status — it survives a Redis restart.

Both processes run from the same codebase. `uvicorn app.main:app` starts the API; `arq app.worker.WorkerSettings` starts the worker.

### The `POST /companies/{ticker}/ingest` endpoint is gone

There is no manual ingest endpoint in Phase 5. The only entry point for ingestion is through `POST /ask`. The agent decides when to ingest based on what the user asks.

### Four new agent tools

| Tool | What it does |
|---|---|
| `list_companies` | Returns all tickers that have at least one filing indexed |
| `list_filings(ticker?)` | Returns each filing's status: `ingested`, `ingesting`, or `failed` |
| `ingest_filing(ticker, form_type, fiscal_year)` | Validates args, creates an `IngestJob` row, enqueues an arq job. Idempotent: returns immediately if already indexed or in-flight |
| `check_ingest_status(job_id, wait?)` | Reads job state from Postgres. If `wait=true`, polls every 3 seconds until the job reaches `done` or `failed` (up to 10 min timeout) |

### New `ingest_jobs` table

Tracks every ingest attempt:

```
id              BigInteger PK
ticker          Text
form_type       Text
fiscal_year     Integer (nullable)
status          Text — "queued" | "running" | "done" | "failed"
error_message   Text (nullable)
job_id          Text (arq job id, unique)
conversation_id BigInteger FK → conversations (nullable, SET NULL on delete)
created_at      DateTime
started_at      DateTime (nullable)
completed_at    DateTime (nullable)
```

Unique constraint on `(ticker, form_type, fiscal_year)` so there is at most one job per filing identity.

### How ingest flows through the system

```
POST /ask  "Ingest NVDA 2024 10-K and tell me their revenue"
  │
  ▼
Agent turn 0
  Claude calls: list_filings(ticker="NVDA")
  → no NVDA row found
  │
  ▼
Agent turn 1
  Claude calls: ingest_filing("NVDA", "10-K", 2024)
  → creates IngestJob row (status=queued)
  → enqueues arq job "ingest_filing_task"
  → returns job_id="ingest-NVDA-10-K-2024"
  │
  ├── [Worker picks up job]
  │     mark status=running
  │     get_cik("NVDA") → CIK
  │     list_filings(CIK) → find FY2024 10-K URL
  │     download_filing(url) → raw HTML → clean text
  │     split_text() → ~700 chunks
  │     embed_texts() → vectors
  │     upsert Filing + Chunks → Postgres
  │     mark status=done
  │
  ▼
Agent turn 2
  Claude calls: check_ingest_status(job_id, wait=true)
  → polls Postgres every 3s until status=done
  → "Ingest complete. The filing is ready to search."
  │
  ▼
Agent turn 3
  Claude calls: search_filings(query="revenue", ticker="NVDA", ...)
  → finds relevant chunks
  │
  ▼
Agent turn 4
  Claude calls: format_answer(response_type="research", answer="NVDA revenue was $60.9B...")
  → returns cited answer to user
```

### Agent wait policy

The agent infers from the question whether to block and wait or just acknowledge:

| Situation | Agent behaviour |
|---|---|
| "Ingest X and tell me Y" (single filing, dependent question) | `ingest_filing` → `check_ingest_status(wait=true)` → search → answer in one turn |
| "Ingest these 10 filings" (bulk, no dependent question) | Enqueue all, acknowledge each, do not block |
| Filing shows `status=ingesting` and user asks about it | Report "still being ingested", offer to wait or be re-asked — never returns empty/hallucinated answer |
| Filing shows `status=failed` | Reports the error, offers to retry |

### Where everything lives (Phase 5 additions)

```
app/
├── worker.py               WorkerSettings + ingest_filing_task (arq worker entrypoint)
├── ingest/
│   └── pipeline.py         upsert_company() + ingest_one_filing() — shared ingest logic
│                           (called by the worker; no FastAPI dependency)
├── tools/registry.py       Now has 5 tools: search_filings + the 4 new ingest tools
├── rag/generate.py         run_agent() now accepts conversation_id + arq_redis;
│                           system prompt extended with ingest workflow rules
├── routers/
│   └── ask.py              Passes conversation_id + arq_redis into run_agent()
└── models.py               + IngestJob model
```

### Key design decisions (Phase 5)

**Why is Postgres the source of truth for job status, not Redis?**
arq's Redis entries expire. If Redis restarts, job history is gone. By mirroring status into `ingest_jobs`, the agent can always answer "what happened to job X?" with a SQL query, even days later.

**Why does the worker receive the `IngestJob.id` (Postgres PK), not the arq job id?**
The Postgres PK is stable before enqueueing and survives retries. The worker loads the row by PK, updates it in-place, and the agent tracks status through the same row — no fragile string matching on arq-generated IDs.

**Why is ingest idempotent at three layers?**
1. `ingest_filing` tool checks for an existing `Filing` row before enqueueing.
2. `IngestJob` has a unique constraint on `(ticker, form_type, fiscal_year)` — the DB rejects duplicates.
3. `ingest_one_filing()` in the worker checks for an existing `Filing.url` before downloading. A crashed-and-restarted job won't double-write.
