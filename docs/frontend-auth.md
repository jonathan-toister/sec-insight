# Frontend Integration Guide

This guide covers everything a frontend application needs to talk to the SEC
Insight API: authentication, all available endpoints with their request/response
shapes, and how to render the answer the API returns.

Scripts and server-to-server callers use the `X-API-Key` header instead of
cookies and can skip the Auth section.

---

## 1. Authentication

SEC Insight uses **httpOnly session cookies** for browser clients. The raw API
key never appears in frontend code; instead you call a login endpoint once, the
server sets a cookie, and the browser sends it automatically on every subsequent
request.

### How it works

```
Browser                              API
  │                                   │
  │  POST /auth/login {password}      │
  │──────────────────────────────────>│  validates LOGIN_PASSWORD
  │                                   │  creates signed JWT
  │  200 + Set-Cookie: sec_session=…  │
  │<──────────────────────────────────│  httpOnly, Secure, SameSite=none
  │                                   │
  │  POST /ask  (cookie sent auto)    │
  │──────────────────────────────────>│  verifies JWT from cookie
  │  200 {answer, sources, …}         │
  │<──────────────────────────────────│
  │                                   │
  │  POST /auth/logout                │
  │──────────────────────────────────>│  clears cookie
  │  200 {ok: true}                   │
  │<──────────────────────────────────│
```

The `sec_session` cookie is `httpOnly` — JavaScript cannot read or modify it.

### Steps to connect

**Step 1 — Get what you need from the backend operator**

| What | Why you need it |
|---|---|
| API base URL (e.g. `https://api.example.com`) | Where all requests go |
| `LOGIN_PASSWORD` value | The password your login screen will submit |
| Your frontend origin (e.g. `https://my-app.vercel.app`) | Must be added to `ALLOWED_ORIGINS` on the server before cookies work cross-origin |

For local development, the API typically runs at `http://localhost:8000`. Ask the
backend operator to set `COOKIE_SECURE=false` and add your local origin to
`ALLOWED_ORIGINS`.

**Step 2 — Add `credentials: "include"` to every fetch call**

This is the single most important setting. Without it the browser silently drops
the cookie on cross-origin requests. Apply it to **every** request.

**Step 3 — Implement login**

```ts
const API = "https://your-api-host.com";  // no trailing slash

export async function login(password: string): Promise<void> {
  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) throw new Error("Invalid password");
  // sec_session cookie is now set — no token to store
}
```

| Status | Meaning |
|---|---|
| `200` | Logged in — `sec_session` cookie is now set |
| `401` | Wrong password |
| `500` | Server is misconfigured (`LOGIN_PASSWORD` or `JWT_SECRET` not set) |

**Step 4 — Implement logout**

```ts
export async function logout(): Promise<void> {
  await fetch(`${API}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
}
```

**Step 5 — Handle session expiry**

The cookie expires after 7 days (configurable on the server). Any API call made
after expiry returns `401`. Catch it and redirect to your login screen:

```ts
if (res.status === 401) {
  router.push("/login");
}
```

### Checklists

**Local development**
- [ ] API base URL set to `http://localhost:8000`
- [ ] Backend operator has set `COOKIE_SECURE=false` and added your local origin to `ALLOWED_ORIGINS`
- [ ] All `fetch` calls include `credentials: "include"`
- [ ] After login: DevTools → Application → Cookies shows `sec_session` with **HttpOnly** checked

**Production**
- [ ] API base URL points to your HTTPS host
- [ ] Backend operator has added your deployed frontend URL to `ALLOWED_ORIGINS` (no trailing slash)
- [ ] All `fetch` calls include `credentials: "include"`

---

## 2. API reference

### `POST /ask`

Ask a natural-language question about indexed SEC filings. The agent searches
the document index, pulls relevant passages, and returns a cited answer.

**Request**

```ts
{
  question: string;          // 3–2000 characters
  conversation_id?: number;  // omit to start a new conversation
}
```

**Response** — see [Section 3](#3-understanding-the-ask-response) for a full
breakdown of each field.

```ts
{
  answer: string;
  sources: string[];
  chunks: ChunkResult[];
  conversation_id: number;
  hypothetical_document: string | null;
}
```

```ts
// ChunkResult
{
  chunk_id: number;
  filing_id: number;
  company: string;
  ticker: string | null;
  form_type: string;         // e.g. "10-K", "10-Q"
  fiscal_year: number | null;
  section: string | null;    // filing section the chunk came from
  text: string;              // full passage text
  distance: float;           // vector similarity — lower = more relevant
  highlights: string[];      // substrings of `text` to emphasise
}
```

**Example fetch**

```ts
export async function ask(
  question: string,
  conversationId?: number,
): Promise<AskResponse> {
  const res = await fetch(`${API}/ask`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, conversation_id: conversationId }),
  });
  if (res.status === 401) throw new AuthError("Session expired");
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}
```

---

### `GET /filings`

Returns the list of SEC filings that have been indexed and are available for
querying.

**No request body.**

**Response** — array of filing objects:

```ts
[
  {
    id: number;
    ticker: string;
    company: string;
    sector: string | null;    // SIC industry description
    form_type: string;        // "10-K" | "10-Q" | …
    fiscal_year: number | null;
    filed_at: string | null;  // ISO 8601 date string
    url: string;              // link to the original SEC filing
  }
]
```

**Example fetch**

```ts
export async function getFilings(): Promise<Filing[]> {
  const res = await fetch(`${API}/filings`, {
    credentials: "include",
  });
  if (res.status === 401) throw new AuthError("Session expired");
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}
```

Typical use: populate a "What's indexed" panel so the user knows which companies
and time periods they can ask about before submitting a question.

---

## 3. Understanding the `/ask` response

The response has four distinct parts that serve different UI purposes.

### `answer`

The main text response — a prose answer grounded in the indexed filings. Render
it as markdown; the model uses bold, bullet lists, and inline citations.

### `sources`

A flat array of human-readable citation strings, for example:

```json
["Apple Inc. 10-K FY2023", "Apple Inc. 10-Q Q2 2024"]
```

Render these as a "Sources" list beneath the answer. Each string corresponds to
one or more chunks but does not carry a direct link — use the `chunks` array if
you need per-chunk filing URLs.

### `chunks`

The raw document passages the agent retrieved to produce the answer. Each chunk
carries metadata about where it came from and a relevance score.

| Field | What it tells you |
|---|---|
| `text` | The full passage text from the filing |
| `distance` | Vector similarity distance — lower means more relevant. Use this to sort or filter chunks before showing them |
| `company` / `ticker` | Who filed it |
| `form_type` / `fiscal_year` | Which filing it came from |
| `section` | Named section within the filing (e.g. "Risk Factors") |
| `highlights` | Substrings of `text` that are most relevant to the question |

Typical display: a collapsible "Evidence" panel showing the top 3–5 chunks
sorted by `distance` ascending.

### `highlights` — rendering emphasized passages

`highlights` is a list of exact substrings found within the chunk's `text`. Use
them to draw the user's eye to the most relevant part of a longer passage.

**How to apply them:**

1. Start with the raw `text` string.
2. For each highlight string, locate its position within `text` using
   `indexOf` (case-sensitive, exact match).
3. Wrap each located span in your highlight element.

```ts
function applyHighlights(text: string, highlights: string[]): string {
  let result = text;
  for (const hl of highlights) {
    // Escape special regex chars before inserting into a pattern
    const escaped = hl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    result = result.replace(
      new RegExp(escaped, "g"),
      `<mark>${hl}</mark>`,
    );
  }
  return result;
}
```

If you are rendering in React, build a segment list instead of injecting raw
HTML:

```tsx
function HighlightedText({ text, highlights }: { text: string; highlights: string[] }) {
  if (highlights.length === 0) return <p>{text}</p>;

  // Build a sorted list of [start, end] ranges to mark
  const ranges: [number, number][] = [];
  for (const hl of highlights) {
    let idx = text.indexOf(hl);
    while (idx !== -1) {
      ranges.push([idx, idx + hl.length]);
      idx = text.indexOf(hl, idx + 1);
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);

  const segments: React.ReactNode[] = [];
  let cursor = 0;
  for (const [start, end] of ranges) {
    if (start > cursor) segments.push(text.slice(cursor, start));
    segments.push(<mark key={start}>{text.slice(start, end)}</mark>);
    cursor = end;
  }
  if (cursor < text.length) segments.push(text.slice(cursor));

  return <p>{segments}</p>;
}
```

### `conversation_id`

Always returned, even for a first question. Pass it back in the next request to
continue the conversation — the API loads the prior message history and answers
in context.

```ts
// First turn — no conversation_id
const first = await ask("What was Apple's revenue in FY2023?");
// first.conversation_id = 42

// Follow-up — pass the id back
const second = await ask("How does that compare to FY2022?", first.conversation_id);
```

Store `conversation_id` in component state (or URL params) for the duration of
a chat session. Discard it to start a fresh conversation.

### `hypothetical_document`

Internal: the query the model generated to improve retrieval. Not intended for
display — you can ignore this field.
