# SPEC — SEC Insight

The detailed plan. `CLAUDE.md` is the short version Claude Code reads; this is the
reference you and it work against. Build phase by phase; don't skip ahead.

## Goal and non-goals

**Goal:** answer investor questions about SEC filings, grounded in the source
documents with citations, and grow into an agent that takes actions over filing
text + structured market data.

**Non-goal:** rebuilding NotebookLM. Every phase should add capability a doc-Q&A
tool can't have: live ingestion, structured-data joins, actions, monitoring.

## Data model

Three tables (pgvector for the embedding column):

- **companies** — `id, ticker, cik, name, sector`. Maps a ticker to its EDGAR CIK.
- **filings** — `id, cik, company, ticker, form_type ('10-K'|'10-Q'),
  fiscal_year, url, filed_at`. One row per document. Unique on
  `(cik, form_type, fiscal_year)` so re-ingesting is idempotent.
- **chunks** — `id, filing_id FK, chunk_index, section, text, embedding VECTOR(1536)`.
  HNSW index on `embedding` with `vector_cosine_ops`.

## Data source: SEC EDGAR

Free, no key. Requirements: a descriptive `User-Agent` header ("Name email") and
roughly 10 requests/second max.

- Ticker → CIK: `https://www.sec.gov/files/company_tickers.json` (one-time map).
- Recent filings per company: `https://data.sec.gov/submissions/CIK##########.json`
  (CIK zero-padded to 10 digits). Gives form types, dates, and document paths.
- The filing itself: the primary `.htm` document referenced in that JSON. Strip
  HTML to clean text before chunking.

## Chunking

- Target ~500–800 tokens per chunk, ~10–15% overlap so meaning isn't cut mid-idea.
- Split on section / paragraph boundaries where possible. 10-Ks have named items
  (e.g. "Item 1A. Risk Factors") — keep the section heading in chunk metadata; it
  makes retrieval and citations far better.
- Store `section` and `chunk_index` so answers can cite "10-K 2024, Item 1A".

## Embeddings

- OpenAI `text-embedding-3-small`, 1536 dims. Batch many chunks per API call.
- The identical function embeds questions at query time. One implementation,
  reused — never two.

---

## Phase 1 — Plain RAG (the foundation)

**Outcome:** for one company, ingest filings and answer questions with citations.

Build, in order:

1. `config.py` + `.env` wired; `db.py` connects and ensures the `vector` extension.
2. `models.py` — the three tables above; create them on startup or via a script.
3. `ingest/edgar.py` — ticker→CIK, list 10-K/10-Q, download + clean a filing.
4. `ingest/chunk.py` — `split_text(text, section) -> list[Chunk]`.
5. `ingest/embed.py` — `embed(texts) -> list[vector]`, batched.
6. `routers/documents.py` — `POST /companies/{ticker}/ingest` runs 3→4→5→store;
   `GET /filings` lists what's indexed.
7. `rag/retrieve.py` — `retrieve(question, filters, k) -> chunks` using
   `ORDER BY embedding <=> :qvec LIMIT k`.
8. `rag/generate.py` — build a prompt that injects chunks and instructs Claude to
   answer ONLY from them and cite each filing; call Claude; return answer+sources.
9. `routers/ask.py` — `POST /ask {question, filters?}` ties retrieve→generate.

**Definition of done:** ingest one real company (e.g. AAPL), ask a question, get a
correct answer that cites the right filing.

## Phase 2 — Tool-calling

**Outcome:** the model decides when to retrieve, instead of fixed code doing it.

1. `tools/registry.py` — define `search_filings(query, company?, form_type?,
   year?, k)` as a JSON schema + a handler that calls `rag.retrieve`.
2. Rewrite `rag/generate.py` into a loop: send the question + tool definitions to
   Claude → if Claude requests a tool, validate the args, run the handler, return
   the result → repeat until Claude returns a final answer.
3. `/ask` now calls this loop. Same endpoint, smarter behavior (no retrieval on
   "thanks"; retrieval when a real question needs it).

**Key skill:** own the whole loop — schema authoring, parsing the tool request,
**validating arguments** (the model can hallucinate bad ones), error handling,
multi-turn. This is the part a no-code agent builder hides from you.

**Definition of done:** a small-talk message returns no tool call; a substantive
question triggers `search_filings` and a cited answer.

## Phase 3 — Actions + structured data

**Outcome:** filing text meets real numbers; the agent does things, not just reads.

1. `tools/registry.py` — add:
   - `get_filing(company, year, form_type)` — fetch a specific document.
   - `compare_filings(company, year1, year2, section)` — retrieve the same section
     from two years and diff/summarize what changed (e.g. risk factors added).
   - `get_stock_price(ticker)` — via `market/prices.py`.
2. `market/prices.py` — wrap a price API (Alpha Vantage / Finnhub, or `yfinance`
   for a no-key start).

Now the agent can answer "how did this company's risk factors change, and where's
the stock now?" by orchestrating multiple tools. **This is the NotebookLM-can't-do
moment** — structured + unstructured, combined, with actions.

**Definition of done:** a single question provably triggers two tools and the
answer combines both results.

## Phase 4 — Monitoring + evals

**Outcome:** proactive, and measurable.

1. **Monitoring:** a scheduled job that polls EDGAR for new filings on tracked
   companies, ingests them, runs `compare_filings` vs. the prior period, and
   emits a "what changed" summary. Pull becomes push.
2. **Evals:** `evals/` holds a test set (`test_set.example.json` is a starter). A
   script runs each question through `/ask` and scores the answer — keyword
   presence to start, optionally an LLM-as-judge later. Treat AI output as
   software with measurable quality, not vibes.

**Definition of done:** new filings are detected automatically and summarized; the
eval script produces a score over the test set.

---

## Stretch (after Phase 4)

- Expose `search_filings` as an **MCP server** so any MCP client can use your data.
- Multi-company screens ("companies that added supply-chain risk language AND lost
  >2% margin"), which require the structured layer to be solid.
- A thin frontend, only if you want it — the engineering value is the backend.

## Guardrails

- Idempotent ingestion (unique constraint on filings); re-running is safe.
- Never trust model-supplied tool args without validation.
- Always cite. Always remind: not investment advice.
- Respect SEC rate limits and User-Agent rules.
