"""Tool-calling registry — Phase 2."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.embed import embed_texts
from app.rag.hyde import generate_hypothetical_document
from app.rag.retrieve import retrieve
from app.rag.retrieve import FilingFilter
from app.schemas import ChunkResult

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "search_filings",
        "description": (
            "Search SEC filings for relevant information. "
            "Use this to find specific data in 10-K or 10-Q filings. "
            "ticker is required — extract it from the question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in the filings.",
                },
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker of the company (e.g. 'AAPL'). Required.",
                },
                "form_type": {
                    "type": "string",
                    "enum": ["10-K", "10-Q"],
                    "description": "Optional form type filter.",
                },
                "fiscal_year": {
                    "type": "integer",
                    "description": "Optional fiscal year filter (e.g. 2023).",
                },
                "k": {
                    "type": "integer",
                    "description": "Number of results to return (1–20, default 6).",
                },
            },
            "required": ["query", "ticker"],
        },
    }
]

_VALID_FORM_TYPES = {"10-K", "10-Q"}


def _validate_search_args(args: dict) -> dict:
    query = args.get("query", "")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("'query' must be a non-empty string.")

    ticker = args.get("ticker", "")
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("'ticker' is required. Identify the company before searching.")

    form_type = args.get("form_type")
    if form_type is not None and form_type not in _VALID_FORM_TYPES:
        raise ValueError(
            f"'form_type' must be one of {sorted(_VALID_FORM_TYPES)}, got '{form_type}'."
        )

    k = args.get("k", 6)
    if not isinstance(k, int):
        k = 6
    k = max(1, min(20, k))

    return {
        "query": query.strip(),
        "ticker": ticker.strip().upper(),
        "form_type": form_type,
        "fiscal_year": args.get("fiscal_year"),
        "k": k,
    }


def _format_result_chunks(
    chunks: list[ChunkResult],
    start_index: int,
    seen: dict[int, int],  # chunk_id -> display index already shown
) -> tuple[list[ChunkResult], str]:
    """Return (new_chunks_only, formatted_text). Deduplicates by chunk_id."""
    parts: list[str] = []
    new_chunks: list[ChunkResult] = []
    for chunk in chunks:
        if chunk.chunk_id in seen:
            parts.append(f"[already shown as [{seen[chunk.chunk_id]}]]")
        else:
            idx = start_index + len(new_chunks)
            seen[chunk.chunk_id] = idx
            header = f"[{idx}] {chunk.company} {chunk.form_type}"
            if chunk.fiscal_year:
                header += f" FY{chunk.fiscal_year}"
            if chunk.section:
                header += f" — {chunk.section}"
            parts.append(f"{header}\n{chunk.text}")
            new_chunks.append(chunk)
    return new_chunks, "\n\n".join(parts)


async def handle_search_filings(
    args: dict,
    session: AsyncSession,
    start_index: int = 1,
    seen: dict[int, int] | None = None,
) -> tuple[list[ChunkResult], str]:
    """Returns (new_chunks, tool_result_content). Deduplicates chunks via seen."""
    hyde_doc = await generate_hypothetical_document(args["query"])
    embeddings = await embed_texts([hyde_doc])
    filters = FilingFilter(
        ticker=args["ticker"],
        form_type=args.get("form_type"),
        fiscal_year=args.get("fiscal_year"),
    )
    chunks = await retrieve(
        embedding=embeddings[0],
        session=session,
        filters=filters,
        k=args["k"],
    )

    if not chunks:
        return [], (
            f"No indexed filings found for ticker '{args['ticker']}' matching your query. "
            "Try different search terms, or check whether this company has been ingested."
        )

    return _format_result_chunks(chunks, start_index=start_index, seen=seen or {})


async def dispatch(
    tool_name: str,
    args: dict,
    session: AsyncSession,
    chunk_accumulator: list[ChunkResult],
    chunk_offset: int,
) -> str:
    """
    Validate args, call the right handler, mutate chunk_accumulator in-place.
    Returns tool_result content to send back to Claude.
    Raises ValueError for unknown tools or invalid args.
    """
    if tool_name == "search_filings":
        validated = _validate_search_args(args)
        seen = {chunk.chunk_id: i + 1 for i, chunk in enumerate(chunk_accumulator)}
        new_chunks, content = await handle_search_filings(
            validated, session, start_index=chunk_offset + 1, seen=seen
        )
        chunk_accumulator.extend(new_chunks)
        return content

    raise ValueError(f"Unknown tool '{tool_name}'.")
