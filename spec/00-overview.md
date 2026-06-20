# SPEC Overview — SEC Insight

The detailed plan, split into one file per phase. `CLAUDE.md` is the short
version Claude Code reads; this folder is the reference you and it work against.
Build phase by phase; don't skip ahead.

## Phase index

| Phase | File | Status |
|---|---|---|
| 1 — Plain RAG | [phase-1-plain-rag.md](phase-1-plain-rag.md) | ✅ Done |
| 2 — Tool-calling | [phase-2-tool-calling.md](phase-2-tool-calling.md) | ✅ Done |
| 3 — Token efficiency baseline | [phase-3-token-efficiency.md](phase-3-token-efficiency.md) | ✅ Done |
| 4 — Conversational guidance | [phase-4-conversational-guidance.md](phase-4-conversational-guidance.md) | ✅ Done |
| 5 — Worker split + ingest tools + persistence | [phase-5-worker-split.md](phase-5-worker-split.md) | ✅ Done |
| 6 — Actions + structured data | [phase-6-actions-structured-data.md](phase-6-actions-structured-data.md) | Planned |
| 7 — New data sources | [phase-7-data-sources.md](phase-7-data-sources.md) | Planned |
| 8 — Monitoring + evals | [phase-8-monitoring-evals.md](phase-8-monitoring-evals.md) | Planned |

Phases 1–2 are the original spec, unchanged. Phases 3–8 reorganize the original
phases 3–4 around four goals: token/context efficiency (phase 3, deliberately
before the conversation features that would multiply its absence); an
interactive, guiding chat with multi-turn history (4) and persisted
conversations (5); a right-sized microservice split (5); and broader data
sources (7). The original phase 3 became phase 6, the original phase 4 became
phase 8.

## Goal and non-goals

**Goal:** answer investor questions about SEC filings, grounded in the source
documents with citations, and grow into an agent that takes actions over filing
text + structured market data.

**Non-goal:** rebuilding NotebookLM. Every phase should add capability a doc-Q&A
tool can't have: live ingestion, structured-data joins, actions, monitoring.

## Data model

Five tables (pgvector for the embedding column):

- **companies** — `id, ticker, cik, name, sic, sic_description,
  state_of_incorporation, exchanges, entity_type`. Maps a ticker to its EDGAR CIK.
- **filings** — `id, company_id FK, form_type ('10-K'|'10-Q'), fiscal_year, url,
  filed_at`. One row per document. Unique on `url` so re-ingesting is idempotent.
- **chunks** — `id, filing_id FK, chunk_index, section, text, embedding VECTOR(1536)`.
  HNSW index on `embedding` with `vector_cosine_ops`.
- **conversations** — `id, title (first question ≤200 chars), created_at,
  updated_at`. One row per chat session.
- **messages** — `id, conversation_id FK, seq, role ('user'|'assistant'), content,
  created_at, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
  model, latency_ms`. One row per turn; assistant messages carry full token telemetry.

Phase 5 adds ingest jobs; phase 7 adds `source_type` on filings/chunks plus a
structured-financials table.

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

## Stretch (after Phase 8)

- Expose `search_filings` as an **MCP server** so any MCP client can use your data.
- Multi-company screens ("companies that added supply-chain risk language AND lost
  >2% margin"), which require the structured layer to be solid.
- A thin frontend, only if you want it — the engineering value is the backend.

## Guardrails

- Idempotent ingestion (unique constraint on filings); re-running is safe.
- Never trust model-supplied tool args without validation.
- Always cite. Always remind: not investment advice.
- Respect SEC rate limits and User-Agent rules.
- Token discipline (from phase 3 on): cache prompts, never resend the same
  chunk twice, log `response.usage` on every call, prefer structured lookups
  over text retrieval for numeric questions.
