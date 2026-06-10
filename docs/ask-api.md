# `/ask` API — Frontend Integration Guide

## Endpoint

```
POST /ask
```

## Request

```json
{
  "question": "What are Apple's biggest risks?",
  "filters": {
    "ticker": "AAPL",
    "form_type": "10-K",
    "fiscal_year": 2023
  },
  "k": 6
}
```

| Field | Required | Description |
|---|---|---|
| `question` | Yes | The investor's plain-English question (3–2000 chars) |
| `filters.ticker` | No | Limit results to a specific company ticker |
| `filters.form_type` | No | Limit to a filing type (`10-K`, `10-Q`, etc.) |
| `filters.fiscal_year` | No | Limit to a specific fiscal year |
| `k` | No | Number of source chunks to retrieve (1–20, default 6) |

---

## Response shape

```json
{
  "answer": "string",
  "sources": ["string"],
  "chunks": [ChunkResult],
  "hypothetical_document": "string"
}
```

### `answer`
A plain-English answer to the question, grounded entirely in the filing excerpts.
Inline citations appear as `[Company Form FY####]` — for example:
`[Apple Inc. 10-K FY2023]`.

Render this as formatted text. You can parse the citation tags to link them to
the corresponding entry in `sources` or to a specific chunk.

Always ends with: `"Disclaimer: This is not investment advice."`

---

### `sources`
Deduplicated list of filings cited in the answer, in the order they first appear.

```json
[
  "Apple Inc. 10-K FY2023 — Risk Factors",
  "Apple Inc. 10-K FY2022 — Risk Factors"
]
```

Use this to render a compact citation list beneath the answer.

---

### `chunks`
The raw source passages Claude used to generate the answer. Each object is a
`ChunkResult`:

```json
{
  "chunk_id": 42,
  "filing_id": 7,
  "company": "Apple Inc.",
  "ticker": "AAPL",
  "form_type": "10-K",
  "fiscal_year": 2023,
  "section": "Risk Factors",
  "text": "Full text of the retrieved passage ...",
  "distance": 0.18,
  "highlights": [
    "We face intense competition in all areas of our business.",
    "Our financial condition and operating results depend substantially on our ability to continually innovate."
  ]
}
```

| Field | Description |
|---|---|
| `chunk_id` / `filing_id` | Internal DB IDs — use for deep-linking or future fetch endpoints |
| `company`, `ticker` | Company name and stock ticker |
| `form_type` | Filing type (e.g. `10-K`, `10-Q`) |
| `fiscal_year` | Fiscal year the filing covers |
| `section` | Section of the filing this chunk came from (e.g. `Risk Factors`) |
| `text` | The full retrieved passage. Show this in a collapsible "source" card. |
| `distance` | Cosine distance (0 = identical, 1 = unrelated). Lower = more relevant. |
| `highlights` | **Verbatim substrings** from `text` that are most relevant to the question. |

#### Rendering highlights

Every string in `highlights` is a verbatim substring of `text`. To highlight:

1. Render the full `text`.
2. For each entry in `highlights`, find its position in `text` with `indexOf`
   and wrap it in `<mark>` (or your highlight component).

```js
function applyHighlights(text, highlights) {
  let result = text;
  for (const phrase of highlights) {
    result = result.replace(phrase, `<mark>${phrase}</mark>`);
  }
  return result;
}
```

`highlights` may be empty if the chunk is contextually relevant but no single
short span stands out — in that case show the full `text` without markup.

#### Suggested source panel layout

- Sort chunks by `distance` ascending (most relevant first).
- Show a label: `{company} {form_type} FY{fiscal_year} — {section}`.
- Show the `text` with highlights applied.
- Use `distance` to drive visual ranking (e.g. a relevance badge or faded
  styling for chunks with `distance > 0.35`).

---

### `hypothetical_document`
An internal artifact from the HyDE (Hypothetical Document Embeddings) retrieval
technique — Claude generates a fake filing passage from the question, which is
then embedded to find real matches.

**Hide this from end users.** It is exposed in the response for debugging only.

---

## Minimal annotated example

```json
{
  "answer": "Apple faces several major risks. First, competition: the company says it faces intense competition across all of its businesses [Apple Inc. 10-K FY2023 — Risk Factors]. Second, supply chain: Apple relies on a small number of suppliers for key components, and any disruption could hurt production [Apple Inc. 10-K FY2023 — Risk Factors]. Disclaimer: This is not investment advice.",

  "sources": [
    "Apple Inc. 10-K FY2023 — Risk Factors"
  ],

  "chunks": [
    {
      "chunk_id": 42,
      "filing_id": 7,
      "company": "Apple Inc.",
      "ticker": "AAPL",
      "form_type": "10-K",
      "fiscal_year": 2023,
      "section": "Risk Factors",
      "text": "We face intense competition in all areas of our business, including from companies that have significantly greater resources than we do. We rely on a limited number of suppliers for certain components used in our products ...",
      "distance": 0.14,
      "highlights": [
        "We face intense competition in all areas of our business",
        "We rely on a limited number of suppliers for certain components"
      ]
    }
  ],

  "hypothetical_document": "Apple Inc. faces risks including competition from Samsung and Google, supply chain concentration in Asia, and regulatory scrutiny in the EU ..."
}
```
