# Getting started with Claude Code

Phases 1–4 are implemented (plain RAG, tool-calling agent loop, token efficiency,
persistent conversations). The next phase to build is Phase 5. Here's how to
orient yourself and continue.

## 1. Open it

Open the `sec-insight/` folder as its own project in VS Code (File → Open
Folder). Open the integrated terminal. Start Claude Code in that terminal. It will
read `CLAUDE.md` automatically — that's your project's standing context.

## 2. One-time setup

```bash
python -m venv .venv && source .venv/bin/activate
pip3 install -r requirements.txt
cp .env.example .env
```

Then edit `.env`:
- `ANTHROPIC_API_KEY` — from console.anthropic.com (generation).
- `OPENAI_API_KEY` — from platform.openai.com (embeddings only).
- `SEC_USER_AGENT` — set to `"Your Name your@email.com"` (SEC requires this).

Sanity check the API skeleton:

```bash
uvicorn app.main:app --reload
# open http://localhost:8000/health  -> {"status":"ok"}
```

## 3. Continue with Claude Code from Phase 5

The golden rule: **one phase at a time**, and run it before moving on. `SPEC.md`
has the detailed steps; `CLAUDE.md` has the build order. Phases 1–4 are done.

Good opening prompt for Phase 5:

> "Read CLAUDE.md and spec/phase-5-worker-split.md. Phases 1–4 are fully
> implemented. Start Phase 5: the async ingest worker, ingest job tracking table,
> and coverage tools (list_companies, list_filings) in tools/registry.py.
> Show me the plan before coding."

The existing implementation is a useful reference:
- `app/rag/generate.py` — the agentic loop with prompt caching
- `app/tools/registry.py` — how tools are defined and dispatched
- `app/routers/ask.py` — how conversation history is loaded and saved
- `app/models.py` — the current DB schema

## 4. Tips for working with Claude Code here

- Ask it to **show a plan before writing code** on each step — cheaper to correct.
- Have it **run the thing** after each piece (ingest a company, hit `/ask`) rather
  than writing many files then debugging all at once.
- Keep `CLAUDE.md` updated as decisions change — it's the memory across sessions.
- Commit after each working step (`git init` first) so you can roll back.
- If it tries to jump ahead a phase, redirect it — the phases build on each other.

## 5. Next milestone

Ingest one company (`POST /companies/AAPL/ingest`) and confirm `POST /ask` returns
a cited answer. Then try a follow-up question using the returned `conversation_id`
to verify conversational history works. That confirms Phases 1–4 are healthy in
your environment before you start Phase 5.
