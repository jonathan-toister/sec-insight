# Phase 12 — Qualitative event extraction

**Status: planned.** Depends on Phase 7 (section tagging, so extraction runs only
on the right chunks). Turns narrative into structured, conclusion-bearing
signals: management changes, product developments, and insider activity. The
value is not the raw event — it's the derived conclusion and the pattern over
time.

**Outcome:** the agent can state and cite a conclusion like "three CFOs in two
years — elevated governance risk" or "two announced products never reached
launch," each grounded in the source text.

## Sources

- **8-K Item 5.02** + DEF 14A → management changes.
- **Business / MD&A sections** (and Phase 7's `get_filing`) → product events.
- **Form 4** → insider transactions.

## Build

1. **Ingest-time extraction pass.** After chunking/section-tagging, run a
   targeted LLM extraction step on the relevant sections only (token-efficient
   because of Phase 7). It writes structured rows, each carrying
   `evidence_chunk_id` back to the source text for citation.

2. **`management_changes` table** — `(company_id, filing_id, date, role,
   person_in, person_out, change_type, signal, rationale, evidence_chunk_id)`.
   `change_type` ∈ appointment / resignation / termination / retirement / death.
   Store a derived `signal` + `rationale` (e.g. CFO departure within 18 months =
   elevated concern; founder/CEO exit = regime change). Detecting *patterns*
   (querying the table over time) is the point — one orderly retirement ≠ serial
   CFO churn.

3. **`product_events` table** — `(company_id, filing_id, date, product_name,
   stage, segment, impact, evidence_chunk_id)`. `stage` ∈ in_R&D / announced /
   launched / discontinued. Tracking stage *transitions* across filings is what
   turns isolated mentions into a pipeline view; tie `segment` to revenue
   segments in `financial_facts` so a product connects to actual numbers, not
   just narrative.

4. **`insider_transactions` table** — `(company_id, filing_id, insider, role,
   txn_type, shares, value, date)` from Form 4. Cluster buys/sells into a
   net-signal over a window.

5. **Tools** — `get_management_changes`, `get_product_pipeline`,
   `get_insider_activity`. Each returns structured rows plus the evidence chunk
   so the agent's claims stay grounded and cited.

## Framing

Conclusions are risk/quality signals feeding the broader analysis (and Phase 10
confidence), not standalone trade calls.

## Definition of done

For a real company, the agent surfaces a management-change pattern, a
product-stage transition, and a net insider signal — each citing the source
filing/chunk.
