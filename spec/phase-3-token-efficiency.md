# Phase 3 — Token efficiency baseline

**Status: implemented.** Small, phase-independent optimizations that
landed before the conversation features (phases 4–5) multiply token usage.
No new capability — same behavior, lower cost, plus the measurement needed to
prove it.

**Outcome:** every API call is cheaper, duplicate context is never resent, and
token usage is logged so later phases can be optimized from data, not guesses.

## Build

1. **Prompt caching** (biggest win). The agent loop in `rag/generate.py` resends
   the system prompt, tool schemas, and all accumulated messages — including
   full chunk texts — on every iteration, at full price. Add
   `cache_control: {"type": "ephemeral"}` to:
   - the system prompt,
   - the last tool schema in the `tools` array,
   - the last message before each new API call.
   Cached reads cost ~10% of base input price; a multi-search loop stops paying
   for the same chunks repeatedly.
2. **Chunk dedup across searches.** `tools/registry.py:dispatch` appends to
   `chunk_accumulator` blindly — two `search_filings` calls (e.g. after a
   rephrase) can return the same chunk and resend its full text. Dedup by
   `chunk_id`; for repeats return a stub like `[already shown as [2]]` instead
   of the text.
3. **HyDE on a cheap model.** `rag/hyde.py` makes a full Claude call per
   retrieval to write a 3–5 sentence passage. Route it to Haiku and cap
   `max_tokens` (~200) — the expensive model adds nothing there.
4. **Usage logging.** `response.usage` (input / output / cache-read /
   cache-write tokens) is currently discarded. Log it per API call — structured
   log line or a small `token_usage` table keyed by request. This becomes eval
   material in phase 8.

## Definition of done

A repeated question shows cache hits in the logged usage; an agent run that
searches twice with overlapping results sends each chunk's text once; HyDE
calls show up in logs on the cheap model; per-request token totals are
queryable.
