# Phase 7 — Section-aware ingestion + retrieval

**Status: planned.** Refactor of the chunk/retrieve pipeline. `chunks` already
carries a `section`; this phase makes sections first-class so retrieval targets
the right part of a filing instead of scanning the whole thing — the analytical
win (better grounding) and the token-efficiency win (fewer, more relevant
chunks) at once.

**Outcome:** a question about MD&A retrieves MD&A chunks; the extraction passes
in Phase 12 can run only on the sections that matter.

## Build

1. **`chunks` — richer section metadata.** Add `item_number` (e.g. `"1A"`,
   `"7"`), `is_table` (bool), `heading` (the nearest section/sub-section title),
   and `fiscal_year` (denormalized from the parent filing for cheap filtering).
   Keep the existing `section` text label for backwards compatibility during
   migration; treat `item_number` + `heading` as the canonical fields going
   forward.

2. **Fix section detection at the HTML layer (`edgar.py`).** The current regex
   runs on plain text *after* HTML is stripped, missing most headings. Fix: before
   converting HTML to text in `download_filing()`, walk the BeautifulSoup tree and
   build a `section_map` — a dict from paragraph index (or character offset) to
   heading text, populated from `<h1>`–`<h4>`, `<b>`, `<strong>`, and bold
   all-caps text patterns. Pass `section_map` into the chunker so headings come
   from document structure, not regex on stripped text.

3. **Three-pass chunker (`chunk.py`).** Replace the single-pass paragraph
   splitter with a three-pass pipeline:
   - **Pass 1 — section split:** use `section_map` (plus the existing Item regex
     as fallback) to split the full text at Item boundaries. Each section carries
     `item_number` and `heading`. Chunks never cross an Item boundary.
   - **Pass 2 — paragraph split:** within each section, apply the existing
     paragraph-boundary chunker to produce candidate chunks at the target size.
   - **Pass 3 — sentence alignment:** if a candidate boundary falls mid-sentence,
     extend or trim to the nearest sentence boundary (`.`, `!`, or `?` followed by
     whitespace and an uppercase letter). A chunk must never begin or end
     mid-sentence.

4. **Retrieval targeting.** Extend `search_filings` with an optional
   `section`/`item_number` filter and a `fiscal_year` filter. The agent (and
   later, the extraction passes) can scope a search to "Risk Factors of the 2024
   10-K" instead of the whole corpus.

5. **`get_filing(company, year, form_type)` tool.** Fetch a specific document's
   sections directly — the basis for section-level comparison in Phase 13's
   diffing.

6. **Backfill — re-ingest from scratch.** Delete all existing `chunks` and
   `filings` rows for previously ingested companies, then re-ingest each filing
   with the new three-pass chunker. This gives every chunk clean `item_number`,
   `heading`, `is_table`, and `fiscal_year` with no inferred or approximate data.
   New embeddings are generated because chunk boundaries change. The backfill
   script (`scripts/backfill_phase7.py`) must be idempotent on re-run.

## Definition of done

A section-scoped question retrieves only chunks from that Item, and a logged
answer uses measurably fewer retrieved chunks/tokens than the same question
unscoped.
