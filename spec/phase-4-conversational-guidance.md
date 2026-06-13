# Phase 4 — Conversational guidance + persistent conversations

**Status: implemented.**

**Outcome:** the API is simplified to a single `question` field, conversations
persist server-side across turns, token usage is tracked per message, and the
agent knows what data it has — guiding users to answerable questions instead of
failing silently.

## Build

1. **Simplified `/ask` API.**
   - `AskRequest` takes only `question` (str) and optional `conversation_id` (int).
   - `filters` and `k` are removed — the tool-calling agent extracts company,
     form type, and year directly from the question.
   - `AskResponse` adds `conversation_id` so the client can continue the conversation.

2. **Conversation persistence** (`conversations` + `messages` tables in Postgres).
   - `conversations`: id, title (first question ≤200 chars), created_at, updated_at.
   - `messages`: id, conversation_id (FK), seq (0-based order), role ('user'|'assistant'),
     content (question text or final answer text), created_at, and per-assistant-message
     token fields: input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
     model, latency_ms.
   - On each `/ask` call: load prior messages from DB → feed as history to the agent →
     save the new user + assistant messages with token data → return conversation_id.
   - Tables are created by SQLAlchemy `create_all` on startup (additive DDL, safe on
     existing data).

3. **Coverage tools** in `tools/registry.py`:
   - `list_companies()` — companies present in the DB (ticker, name, filing count).
   - `list_filings(ticker)` — which filings exist for a company: form type,
     fiscal year, filed date. Args validated like every other tool.
   - Token rule: return compact lines, not JSON dumps —
     `AAPL: 10-K FY2022–24, 10-Q FY2024 Q1–3` beats 40 lines of objects.

4. **System prompt** in `rag/generate.py` — instruct the model to:
   - check coverage first (`list_filings`) when a question names a company/year;
   - tell the user what IS available when the requested data isn't;
   - suggest concrete, answerable follow-up questions;
   - offer to ingest missing filings (the offer only — actual ingestion from
     chat lands in phase 5).

5. **History compaction** (applied when loading prior messages for a new turn):
   - Prior messages are stored as plain question/answer text (not raw tool-call
     wire format) so history is compact and self-contained.
   - Cap history at the last N turns if needed to avoid unbounded context growth.

## Definition of done

- `POST /ask` with no `conversation_id` returns one in the response.
- A follow-up call with that `conversation_id` produces a contextually aware answer.
- `messages` table rows include non-null `input_tokens` and `latency_ms`.
- Asking about a company not in the DB returns a helpful reply listing what is
  available, not a hallucination.
