# SEC Insight — For Dummies

## What is this, in one sentence?

You type a question like *"What were Apple's biggest risks in 2023?"* and the system finds the answer inside Apple's actual SEC filings, then quotes the specific filing as a source. Think of it as Google over legal documents, with citations.

---

## Key concepts

**SEC filing** — When a public company (Apple, Tesla, etc.) wants to raise money or stay listed on a stock exchange, the law requires them to publish detailed reports. The two main ones:
- **10-K** — the annual report (yearly). Deep dive into the business, risks, finances.
- **10-Q** — the quarterly report. A shorter update every 3 months.

These are the raw documents this system reads.

**Ticker** — The short stock symbol for a company. `AAPL` = Apple, `MSFT` = Microsoft, `TSLA` = Tesla. Every API that asks "which company?" takes a ticker as shorthand. It's just a lookup key.

**CIK** — The SEC's internal ID number for every company. EDGAR (the SEC's document database) doesn't know what "AAPL" means — it wants a CIK like `0000320193`. The system's first job is always: ticker → CIK → filings.

**EDGAR** — The SEC's free public database of all filings. No API key needed. The system scrapes it automatically.

**RAG (Retrieval-Augmented Generation)** — The core technique. Instead of asking an AI to answer from memory (which leads to hallucinations), you:
1. Find the relevant passages from real documents (retrieval).
2. Hand those passages to the AI and say "answer ONLY using this" (generation).
3. The AI cites which passage it used.

**Embeddings** — A way to turn text into a list of numbers (a "vector") that captures *meaning*. Two sentences that mean the same thing will have similar numbers, even if the words differ. This is how retrieval works: convert the user's question to a vector, then find the document chunks whose vectors are closest. OpenAI's API does this step.

**pgvector** — A PostgreSQL extension that lets the database store and search those vectors efficiently.

**Chunk** — A 10-K is 100+ pages. It's split into ~500-word pieces (chunks) so the vector search can be precise. Each chunk remembers which section it came from (e.g. "Item 1A. Risk Factors") so the citation is meaningful.

---

## The APIs, plain English

### `POST /companies/{ticker}/ingest`
> *"Go download and index this company's filings."*

You call this once per company before you can ask questions. It:
1. Looks up the ticker (e.g. `AAPL`) to get Apple's SEC ID (CIK).
2. Fetches Apple's recent 10-K and 10-Q documents from EDGAR.
3. Strips the raw HTML to clean text.
4. Splits the text into chunks (~500 words each).
5. Converts each chunk to a vector (via OpenAI embeddings).
6. Saves everything to the PostgreSQL database.

After this runs, the database has hundreds of rows representing Apple's filings, ready to be searched.

`{ticker}` in the URL is just replaced with the actual symbol, e.g. `/companies/AAPL/ingest`.

---

### `GET /filings`
> *"What have you already indexed?"*

Lists the companies and filing documents already in the database. Useful to check "did the ingest work?" before asking questions.

---

### `POST /ask`
> *"Answer my question about SEC filings."*

You send:
```json
{
  "question": "What were Apple's biggest risks in 2023?",
  "conversation_id": 42
}
```

`conversation_id` is optional — omit it to start a new conversation, or pass one
returned from a previous call to continue where you left off.

You get back:
```json
{
  "answer": "Apple's biggest risks included... [Apple Inc. 10-K FY2023]",
  "sources": ["Apple Inc. 10-K FY2023 — Risk Factors"],
  "chunks": [...],
  "conversation_id": 42
}
```

Internally: Claude runs an agent loop — it calls `search_filings` (which uses
HyDE + pgvector) one or more times until it has enough context, then calls
`format_answer` to produce the cited answer. The conversation is saved to the DB
so follow-up questions have history.

---

## The data pipeline (how a filing becomes an answer)

```
EDGAR website  →  edgar.py  →  chunk.py    →  embed.py  →  PostgreSQL
(raw HTML)        (clean       (500-word       (vectors)    (chunks +
                   text)        pieces)                      embeddings)

User question  →  hyde.py  →  embed.py  →  retrieve.py  →  generate.py  →  Answer
               (write a fake   (vector)     (find closest   (Claude agent
                filing passage)              chunks)         loop with
                                                             citations)
```

---

## Why this is more powerful than "ChatGPT with file upload"

| Feature | ChatGPT file upload | This system |
|---|---|---|
| Fetches new filings automatically | No — you upload manually | Yes — pulls from EDGAR live |
| Works across many companies | No | Yes — ingest any ticker |
| Cites the exact filing section | Loosely | Yes, mandatory |
| Can compare two years of filings | No | Yes (Phase 3) |
| Detects when new filings appear | No | Yes (Phase 4) |
| Joins filing text with stock price | No | Yes (Phase 3) |

---

## Build phases (what's built when)

| Phase | What works | Status |
|---|---|---|
| **Phase 1** | Ingest one company, ask one question, get a cited answer | ✅ Done |
| **Phase 2** | The AI decides *when* to search (tool-calling) — smarter retrieval | ✅ Done |
| **Phase 3** | Token efficiency: prompt caching, chunk dedup, HyDE on Haiku, usage logging | ✅ Done |
| **Phase 4** | Conversational memory: follow-up questions work; conversations saved to DB | ✅ Done |
| **Phase 5** | Async ingest worker; coverage tools so the AI knows what's indexed | Planned |
| **Phase 6** | AI can fetch stock prices and diff two filings year-over-year | Planned |
| **Phase 7** | New data sources: earnings calls, press releases | Planned |
| **Phase 8** | Auto-detects new filings; answers are scored automatically | Planned |
