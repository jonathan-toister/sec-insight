# Phase 4 — Conversational guidance + coverage tools

**Status: planned.** No infrastructure change; deepens the phase-2 tool loop
and gives an immediate UX payoff.

**Outcome:** the chat knows what data it has, tells the user, guides them to
answerable questions instead of failing silently on uncovered companies/years —
and holds a multi-turn conversation without exploding token usage.

## Build

1. **Coverage tools** in `tools/registry.py`:
   - `list_companies()` — companies present in the DB (ticker, name, filing count).
   - `list_filings(ticker)` — which filings exist for a company: form type,
     fiscal year, filed date. Args validated like every other tool.
   - Token rule: return compact lines, not JSON dumps —
     `AAPL: 10-K FY2022–24, 10-Q FY2024 Q1–3` beats 40 lines of objects.
2. **System prompt** in `rag/generate.py` — instruct the model to:
   - check coverage first (`list_filings`) when a question names a company/year;
   - tell the user what IS available when the requested data isn't;
   - suggest concrete, answerable follow-up questions;
   - offer to ingest missing filings (the offer only — actual ingestion from
     chat lands in phase 5).
3. **Multi-turn conversation, stateless form.** `/ask` accepts a `messages`
   array; the client resends history each turn. No session tables yet — that's
   deliberate (server-side persistence lands in phase 5, where the worker makes
   it necessary). This matches the Anthropic API shape, so it maps directly
   onto the existing agent loop.
4. **History compaction** (the phase-3 mindset applied to history):
   - when rebuilding the messages array, replace prior turns' tool-result chunk
     payloads with a stub ("[results for 'risk factors' shown previously]") —
     the model already answered from them;
   - cap history at the last N turns;
   - keep prompt caching aligned: cache breakpoint on the last history message.

## Definition of done

Asking about a company that isn't ingested returns a helpful reply listing what
is available and suggesting next questions — not a hallucinated or empty answer.
A follow-up turn ("ok, what about their 2024 10-K?") works with context intact,
and logged usage shows history turns are not resending old chunk text.
