# Phase 2 — Tool-calling

**Status: ✅ implemented.** Kept verbatim from the original SPEC for reference.

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
