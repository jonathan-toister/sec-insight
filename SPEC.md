# SPEC — SEC Insight

The spec now lives in the [`spec/`](spec/) folder, one file per phase.

Start with [`spec/00-overview.md`](spec/00-overview.md) — it holds the goal,
data model, EDGAR notes, chunking/embedding conventions, guardrails, and the
phase index:

- [Phase 1 — Plain RAG](spec/phase-1-plain-rag.md) ✅
- [Phase 2 — Tool-calling](spec/phase-2-tool-calling.md) ✅
- [Phase 3 — Token efficiency baseline](spec/phase-3-token-efficiency.md) ✅
- [Phase 4 — Conversational guidance](spec/phase-4-conversational-guidance.md) ✅
- [Phase 5 — Worker split + ingest tools + persistence](spec/phase-5-worker-split.md) ✅
- [Phase 6 — Schema hardening + data integrity](spec/phase-6-schema-hardening.md) ✅
- [Phase 7 — Section-aware ingestion + retrieval](spec/phase-7-section-aware-retrieval.md) ✅
- [Phase 8 — Structured financials (XBRL)](spec/phase-8-structured-financials-xbrl.md) ✅
- [Phase 9 — Prices + macro](spec/phase-9-prices-macro.md)
- [Phase 10 — Valuation engine](spec/phase-10-valuation-engine.md)
- [Phase 11 — Sector context](spec/phase-11-sector-context.md)
- [Phase 12 — Qualitative event extraction](spec/phase-12-event-extraction.md)
- [Phase 13 — Monitoring + evals](spec/phase-13-monitoring-evals.md)

Build phase by phase; don't skip ahead.
