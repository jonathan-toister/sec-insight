# How SEC Insight Works — Phase 2: The Agent Loop

This document explains how the `/ask` endpoint works after Phase 2. No finance or ML background needed.

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
    └── handle_search_filings()  Embeds query → vector search → return chunks
```

---

## Full Request Lifecycle (Sequence Diagram)

```
You          /ask router      run_agent()        Claude       PostgreSQL
 │                │                │                │              │
 │  POST /ask     │                │                │              │
 │─────────────>  │                │                │              │
 │                │  run_agent()   │                │              │
 │                │───────────────>│                │              │
 │                │                │  question +    │              │
 │                │                │  tool schemas  │              │
 │                │                │───────────────>│              │
 │                │                │                │              │
 │                │                │  search_filings│              │
 │                │                │  (ticker="KO") │              │
 │                │                │<───────────────│              │
 │                │                │                │              │
 │                │                │  embed query   │              │
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
 │                │  AskResponse   │                │              │
 │                │<───────────────│                │              │
 │  200 OK        │                │                │              │
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
