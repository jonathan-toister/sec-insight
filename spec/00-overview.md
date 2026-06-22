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
| 6 — Schema hardening + data integrity | [phase-6-schema-hardening.md](phase-6-schema-hardening.md) | ✅ Done |
| 7 — Section-aware ingestion + retrieval | [phase-7-section-aware-retrieval.md](phase-7-section-aware-retrieval.md) | ✅ Done |
| 8 — Structured financials (XBRL) | [phase-8-structured-financials-xbrl.md](phase-8-structured-financials-xbrl.md) | ✅ Done |
| 9 — Prices + macro | [phase-9-prices-macro.md](phase-9-prices-macro.md) | Planned |
| 10 — Valuation engine + model registry | [phase-10-valuation-engine.md](phase-10-valuation-engine.md) | Planned |
| 11 — Sector context | [phase-11-sector-context.md](phase-11-sector-context.md) | Planned |
| 12 — Qualitative event extraction | [phase-12-event-extraction.md](phase-12-event-extraction.md) | Planned |
| 13 — Monitoring + evals | [phase-13-monitoring-evals.md](phase-13-monitoring-evals.md) | Planned |

Phases 1–8 are built. Phases 9–13 turn the RAG-over-filings engine into a
long-term investing analyst. They go **improvements first, then additions**:
phases 6–7 harden the existing schema and make retrieval section-aware; phases
8–9 add structured data (XBRL fundamentals, prices, macro); phases 10–11 add the
valuation engine and sector context that consume it; phase 12 extracts
qualitative signals (management changes, products, insiders); phase 13 makes the
system proactive and measurable. The old planned phases (actions+structured
data, data sources, monitoring+evals) are absorbed here — their good ideas
(`compare_filings`, the XBRL source, the citation/`source_type` model, the eval
harness) live on inside the relevant new phase.

**Dependencies:** 10 needs 8+9; 11 needs 8; 12 needs 7; 13 needs 12. The whole
arc keeps to the four differentiators — live ingestion, structured-data joins,
actions, monitoring — over a nicer chatbot.

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

Phase 5 adds ingest jobs. Phases 6–13 extend the model:

- **Phase 6** adds `period_of_report` / `accession_number` / `source_type` on
  `filings`, `sector`/`industry`/`fiscal_year_end` on `companies`, and a
  point-in-time contract (`period_of_report` + `filed_at` on every fact).
- **Phase 7** adds `item_number` / `is_table` / `heading` / `fiscal_year` on
  `chunks`.
- **Phase 8** adds `financial_facts` + `metric_dimensions` (XBRL, queried by
  SQL, not embedded).
- **Phase 9** adds `prices` + `macro_series`.
- **Phase 10** adds `valuation_models` (registry) + `valuations` (cache).
- **Phase 11** adds `sectors` / `sector_profiles` + `company_peers`.
- **Phase 12** adds `management_changes`, `product_events`,
  `insider_transactions`, each linked to an `evidence_chunk_id` for citation.

Guiding rule across all of them: extract structure at ingest, query it as rows,
retrieve text only to explain — the analytical and token-efficiency win at once.

## Data source: SEC EDGAR

Free, no key. Requirements: a descriptive `User-Agent` header ("Name email") and
roughly 10 requests/second max.

- Ticker → CIK: `https://www.sec.gov/files/company_tickers.json` (one-time map).
- Recent filings per company: `https://data.sec.gov/submissions/CIK##########.json`
  (CIK zero-padded to 10 digits). Gives form types, dates, and document paths.
- The filing itself: the primary `.htm` document referenced in that JSON. Strip
  HTML to clean text before chunking.

## Chunking

Phase 7 upgrades ingestion to a three-pass pipeline:
1. **Section split** — identify Item boundaries from HTML heading structure (extracted
   before HTML is stripped) plus a regex fallback. Chunks never cross Item boundaries.
2. **Paragraph split** — within each section, split at paragraph boundaries to reach
   the target chunk size (~500–800 tokens).
3. **Sentence alignment** — trim or extend any boundary that falls mid-sentence. A
   chunk must never begin or end in the middle of a sentence.

Store `item_number`, `heading`, and `chunk_index` per chunk for scoped retrieval and
citations ("10-K 2024, Item 1A").

## Embeddings

- OpenAI `text-embedding-3-small`, 1536 dims. Batch many chunks per API call.
- The identical function embeds questions at query time. One implementation,
  reused — never two.

## Cross-referencing architecture (Phases 8–13)

Each data type is stored in the format that fits its access pattern:

- **Text** (filing narrative) → pgvector chunks, retrieved by cosine similarity.
- **Structured numbers** (XBRL facts, prices, macro) → SQL rows, queried directly.
- **Events** (management changes, product transitions, insider activity) → typed rows
  with `evidence_chunk_id` linking back to the source chunk for citation.
- **Valuations** → cached result rows in `valuations` table; inputs traceable to
  `financial_facts` / `prices` / `macro_series`.

The agent loop keeps these streams separate: text chunks flow into the existing
`all_chunks` accumulator; structured data is formatted inline in tool-result strings.
For investment propositions, the **`analyze_company(ticker, focus=[])` compound tool**
(added in Phase 10) batches financials + prices + valuation + sector context into one
call, keeping full-analysis turns to ~3–4 instead of 8+. A dedicated
`"investment_analysis"` response type for `format_answer` (also Phase 10) structures
the final answer into summary, valuation, risk, and verdict sections.

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
