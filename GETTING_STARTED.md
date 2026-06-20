# Getting started with Claude Code

This file covers the Claude Code workflow for continuing development. For
project setup and running the service, see **README.md** first.

Phases 1–5 are implemented (plain RAG, tool-calling agent loop, token efficiency,
persistent conversations, async ingest worker). The next phase to build is Phase 6.

## 1. Open it

Open the `sec-insight/` folder as its own project in VS Code (File → Open
Folder). Open the integrated terminal. Start Claude Code in that terminal. It will
read `CLAUDE.md` automatically — that's your project's standing context.

## 2. Continue with Claude Code from Phase 6

The golden rule: **one phase at a time**, and run it before moving on. `SPEC.md`
has the detailed steps; `CLAUDE.md` has the build order. Phases 1–5 are done.

Good opening prompt for Phase 6:

> "Read CLAUDE.md and spec/phase-6-actions-structured-data.md. Phases 1–5 are fully
> implemented. Start Phase 6: the compare_filings and get_stock_price tools.
> Show me the plan before coding."

The existing implementation is a useful reference:
- `app/rag/generate.py` — the agentic loop with prompt caching
- `app/tools/registry.py` — how tools are defined and dispatched
- `app/routers/ask.py` — how conversation history is loaded and saved
- `app/models.py` — the current DB schema

## 3. Tips for working with Claude Code here

- Ask it to **show a plan before writing code** on each step — cheaper to correct.
- Have it **run the thing** after each piece (ingest a company, hit `/ask`) rather
  than writing many files then debugging all at once.
- Keep `CLAUDE.md` updated as decisions change — it's the memory across sessions.
- Commit after each working step so you can roll back.
- If it tries to jump ahead a phase, redirect it — the phases build on each other.

## 4. Next milestone

Ask the agent to ingest a company via `POST /ask` with a question like
`"Please ingest AAPL's 2024 10-K"`. Confirm the job completes and that a
follow-up question returns a cited answer. Then try a follow-up using the
returned `conversation_id` to verify conversational history works. That
confirms Phases 1–5 are healthy in your environment before you start Phase 6.
