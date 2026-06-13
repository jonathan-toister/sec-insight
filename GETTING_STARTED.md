# Getting started with Claude Code

This project is scaffolded but the implementation is intentionally left as stubs
so you build it with Claude Code. Here's how to pick it up.

## 1. Open it

Open the `sec-insight/` folder as its own project in VS Code (File → Open
Folder). Open the integrated terminal. Start Claude Code in that terminal. It will
read `CLAUDE.md` automatically — that's your project's standing context.

## 2. One-time setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
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

## 3. Build with Claude Code, phase by phase

The golden rule: **one phase at a time**, and run it before moving on. `SPEC.md`
has the detailed steps; `CLAUDE.md` has the build order. Good opening prompts:

> "Read CLAUDE.md and SPEC.md. We're doing Phase 1 only. Start by implementing
> `app/db.py`, `app/models.py`, and `scripts/init_db.sql` for the filings and
> chunks tables with a pgvector embedding column. Show me the plan before coding."

Then proceed step by step:

> "Now implement `app/ingest/edgar.py`: ticker→CIK, list 10-K/10-Q filings for a
> company, and download + clean the primary document to text. Use the SEC
> endpoints in SPEC.md and send the User-Agent from settings."

> "Implement chunking and embeddings (`chunk.py`, `embed.py`), then the ingest
> endpoint in `routers/documents.py`. Let's ingest AAPL and verify rows land in
> the DB."

> "Implement retrieval and generation, then `POST /ask`. Test it with a real
> question about Apple's risk factors and confirm the answer cites the filing."

When Phase 1 runs end to end, move to Phase 2 (tool-calling), and so on.

## 4. Tips for working with Claude Code here

- Ask it to **show a plan before writing code** on each step — cheaper to correct.
- Have it **run the thing** after each piece (ingest a company, hit `/ask`) rather
  than writing many files then debugging all at once.
- Keep `CLAUDE.md` updated as decisions change — it's the memory across sessions.
- Commit after each working step (`git init` first) so you can roll back.
- If it tries to jump ahead a phase, redirect it — the phases build on each other.

## 5. First milestone to aim for

Ingest one company's latest 10-K and get a correct, cited answer to one real
question. That's Phase 1 done and already something worth showing. Everything
after that — tool-calling, diffs, prices, monitoring — is what makes it more than
a doc-chat toy.
