# Phase 1 — Plain RAG (the foundation)

**Status: ✅ implemented.** Kept verbatim from the original SPEC for reference.

**Outcome:** for one company, ingest filings and answer questions with citations.

Build, in order:

1. `config.py` + `.env` wired; `db.py` connects and ensures the `vector` extension.
2. `models.py` — the three tables (see [00-overview.md](00-overview.md)); create
   them on startup or via a script.
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
