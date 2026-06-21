"""Tool-calling registry — Phase 5."""
import asyncio

from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.embed import embed_texts
from app.models import Chunk, Company, Filing, IngestJob
from app.rag.hyde import generate_hypothetical_document
from app.rag.retrieve import FilingFilter, retrieve
from app.schemas import ChunkResult

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "search_filings",
        "description": (
            "Search SEC filings for relevant information. "
            "Use this to find specific data in 10-K or 10-Q filings. "
            "ticker is required — extract it from the question. "
            "Use item_number to restrict to a specific section (e.g. '1A' for Risk Factors, "
            "'7' for MD&A, '8' for Financial Statements)."
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
                "item_number": {
                    "type": "string",
                    "description": (
                        "Optional SEC Item number filter (e.g. '1' for Business, "
                        "'1A' for Risk Factors, '7' for MD&A, '8' for Financial Statements). "
                        "Scopes retrieval to that section only."
                    ),
                },
                "k": {
                    "type": "integer",
                    "description": "Number of results to return (1–20, default 6).",
                },
            },
            "required": ["query", "ticker"],
        },
    },
    {
        "name": "list_companies",
        "description": (
            "List all companies for which at least one filing has been indexed or is "
            "currently being ingested. Call this when the user asks what companies are "
            "available, or to verify a ticker before searching."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_filings",
        "description": (
            "List filings for a company (or all companies) with their ingestion status: "
            "'ingested' (ready to search), 'ingesting' (job in progress), or 'failed'. "
            "Call before search_filings to detect gaps and avoid empty search results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker (e.g. 'AAPL'). Omit to list all companies.",
                },
            },
        },
    },
    {
        "name": "ingest_filing",
        "description": (
            "Trigger background ingestion of a specific SEC filing. Idempotent: returns "
            "the existing status if already indexed or in progress. Returns a job_id for "
            "tracking with check_ingest_status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker (e.g. 'AAPL')."},
                "form_type": {
                    "type": "string",
                    "enum": ["10-K", "10-Q"],
                    "description": "Filing type.",
                },
                "fiscal_year": {
                    "type": "integer",
                    "description": "Fiscal year of the filing (e.g. 2023).",
                },
            },
            "required": ["ticker", "form_type", "fiscal_year"],
        },
    },
    {
        "name": "check_ingest_status",
        "description": (
            "Check the status of an ingest job. Set wait=true to block internally "
            "until the job reaches a terminal state (done/failed), up to 10 minutes. "
            "Use wait=true when the user's question depends on the filing being ready — "
            "it allows you to answer in the same turn without a second request."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "job_id returned by ingest_filing.",
                },
                "wait": {
                    "type": "boolean",
                    "description": (
                        "If true, poll until done/failed (max 10 min). "
                        "Use for single-filing dependent questions."
                    ),
                },
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "get_filing",
        "description": (
            "Retrieve the section structure of a specific indexed filing — returns its "
            "Item numbers and headings with chunk counts. Use this before a targeted "
            "search to see which sections are available, or to orient section-level comparisons."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker of the company (e.g. 'AAPL').",
                },
                "form_type": {
                    "type": "string",
                    "enum": ["10-K", "10-Q"],
                    "description": "Filing type.",
                },
                "fiscal_year": {
                    "type": "integer",
                    "description": "Fiscal year of the filing (e.g. 2024).",
                },
            },
            "required": ["ticker", "form_type", "fiscal_year"],
        },
    },
]

_VALID_FORM_TYPES = {"10-K", "10-Q"}

_WAIT_TIMEOUT = 600.0   # seconds
_POLL_INTERVAL = 3.0    # seconds


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

    item_number = args.get("item_number")
    if item_number is not None:
        item_number = str(item_number).strip().upper()

    return {
        "query": query.strip(),
        "ticker": ticker.strip().upper(),
        "form_type": form_type,
        "fiscal_year": args.get("fiscal_year"),
        "item_number": item_number,
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
            if chunk.item_number and chunk.heading:
                header += f" — Item {chunk.item_number}. {chunk.heading}"
            elif chunk.section:
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
        item_number=args.get("item_number"),
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


async def handle_list_companies(session: AsyncSession) -> str:
    rows = (
        await session.execute(
            select(Company.ticker, Company.name).order_by(Company.ticker)
        )
    ).all()

    if not rows:
        return "No companies are currently indexed."

    lines = [f"{r.ticker} — {r.name}" for r in rows]
    return f"Companies in the index ({len(lines)}):\n" + "\n".join(lines)


async def handle_list_filings(args: dict, session: AsyncSession) -> str:
    ticker_filter = args.get("ticker", "").strip().upper() or None

    # Ingested filings (Filing rows joined with Company)
    stmt = (
        select(
            Company.ticker,
            Company.name,
            Filing.form_type,
            Filing.fiscal_year,
            Filing.filed_at,
        )
        .join(Company, Filing.company_id == Company.id)
        .order_by(Company.ticker, Filing.form_type, Filing.fiscal_year.desc().nulls_last())
    )
    if ticker_filter:
        stmt = stmt.where(Company.ticker == ticker_filter)

    ingested_rows = (await session.execute(stmt)).all()

    # In-flight / failed jobs (IngestJob rows not yet 'done')
    job_stmt = (
        select(
            IngestJob.ticker,
            IngestJob.form_type,
            IngestJob.fiscal_year,
            IngestJob.status,
            IngestJob.error_message,
            IngestJob.created_at,
        )
        .where(IngestJob.status != "done")
        .order_by(IngestJob.ticker, IngestJob.created_at.desc())
    )
    if ticker_filter:
        job_stmt = job_stmt.where(IngestJob.ticker == ticker_filter)

    job_rows = (await session.execute(job_stmt)).all()

    lines: list[str] = []

    for r in ingested_rows:
        fy = f" FY{r.fiscal_year}" if r.fiscal_year else ""
        filed = f" (filed {r.filed_at})" if r.filed_at else ""
        lines.append(f"  {r.ticker} — {r.name}: {r.form_type}{fy}{filed} [ingested]")

    for r in job_rows:
        fy = f" FY{r.fiscal_year}" if r.fiscal_year else ""
        display_status = "ingesting" if r.status in ("queued", "running") else r.status
        detail = f" — error: {r.error_message}" if r.status == "failed" and r.error_message else ""
        lines.append(f"  {r.ticker}: {r.form_type}{fy} [{display_status}]{detail}")

    if not lines:
        subject = f"ticker {ticker_filter}" if ticker_filter else "any company"
        return f"No filings found for {subject}."

    return f"Filing coverage ({len(lines)} entries):\n" + "\n".join(lines)


async def handle_get_filing(args: dict, session: AsyncSession) -> str:
    ticker = str(args.get("ticker", "")).strip().upper()
    form_type = str(args.get("form_type", "")).strip()
    fiscal_year = args.get("fiscal_year")

    if not ticker:
        return "Error: 'ticker' is required."
    if form_type not in _VALID_FORM_TYPES:
        return f"Error: 'form_type' must be one of {sorted(_VALID_FORM_TYPES)}."
    if not isinstance(fiscal_year, int):
        return "Error: 'fiscal_year' must be an integer."

    filing_row = await session.scalar(
        select(Filing.id)
        .join(Company, Filing.company_id == Company.id)
        .where(Company.ticker == ticker)
        .where(Filing.form_type == form_type)
        .where(Filing.fiscal_year == fiscal_year)
    )

    if filing_row is None:
        return (
            f"No indexed filing found for {ticker} {form_type} FY{fiscal_year}. "
            "Use list_filings to see what is available, or ingest_filing to index it."
        )

    # Group chunks by item_number + heading, count them
    rows = (
        await session.execute(
            select(
                Chunk.item_number,
                Chunk.heading,
                sqlfunc.count(Chunk.id).label("chunk_count"),
            )
            .where(Chunk.filing_id == filing_row)
            .group_by(Chunk.item_number, Chunk.heading)
            .order_by(Chunk.item_number.nulls_first(), Chunk.heading)
        )
    ).all()

    if not rows:
        return f"Filing {ticker} {form_type} FY{fiscal_year} is indexed but has no chunks."

    lines = [f"{ticker} {form_type} FY{fiscal_year} — sections:"]
    for r in rows:
        item = f"Item {r.item_number}" if r.item_number else "(preamble)"
        hdg = f". {r.heading}" if r.heading else ""
        lines.append(f"  {item}{hdg}  [{r.chunk_count} chunks]")

    return "\n".join(lines)


async def handle_ingest_filing(
    args: dict,
    session: AsyncSession,
    arq_redis,
    conversation_id: int | None,
) -> str:
    if arq_redis is None:
        return "Error: Redis not available. Cannot queue ingest job."

    ticker = str(args.get("ticker", "")).strip().upper()
    form_type = str(args.get("form_type", "")).strip()
    fiscal_year = args.get("fiscal_year")

    if not ticker:
        return "Error: 'ticker' is required."
    if form_type not in _VALID_FORM_TYPES:
        return f"Error: 'form_type' must be one of {sorted(_VALID_FORM_TYPES)}."
    if not isinstance(fiscal_year, int):
        return "Error: 'fiscal_year' must be an integer."

    # Already indexed?
    existing_filing = await session.scalar(
        select(Filing.id)
        .join(Company, Filing.company_id == Company.id)
        .where(Company.ticker == ticker)
        .where(Filing.form_type == form_type)
        .where(Filing.fiscal_year == fiscal_year)
    )
    if existing_filing:
        return (
            f"{ticker} {form_type} FY{fiscal_year} is already indexed. "
            "You can search it now."
        )

    # Active job already running?
    existing_job = await session.scalar(
        select(IngestJob)
        .where(IngestJob.ticker == ticker)
        .where(IngestJob.form_type == form_type)
        .where(IngestJob.fiscal_year == fiscal_year)
    )

    if existing_job and existing_job.status in ("queued", "running"):
        return (
            f"Ingest for {ticker} {form_type} FY{fiscal_year} is already in progress. "
            f"job_id={existing_job.job_id}"
        )

    if existing_job:
        # Reset a failed job and re-enqueue.
        existing_job.status = "queued"
        existing_job.error_message = None
        existing_job.started_at = None
        existing_job.completed_at = None
        existing_job.conversation_id = conversation_id
        await session.flush()
        job_row_id = existing_job.id
        is_retry = True
    else:
        job = IngestJob(
            ticker=ticker,
            form_type=form_type,
            fiscal_year=fiscal_year,
            status="queued",
            conversation_id=conversation_id,
        )
        session.add(job)
        await session.flush()
        job_row_id = job.id
        is_retry = False

    arq_job_id = f"ingest-{ticker}-{form_type}-{fiscal_year}"
    if is_retry:
        arq_job_id += "-retry"

    arq_result = await arq_redis.enqueue_job(
        "ingest_filing_task",
        job_row_id,
        _job_id=arq_job_id,
    )

    # arq returns None if a job with that _job_id is already queued in Redis.
    actual_job_id = arq_result.job_id if arq_result else arq_job_id

    if existing_job:
        existing_job.job_id = actual_job_id
    else:
        # Reload to set job_id (flush gave us the PK but not the ORM object reference)
        job_obj = await session.get(IngestJob, job_row_id)
        if job_obj:
            job_obj.job_id = actual_job_id

    await session.commit()

    action = "Re-queued" if is_retry else "Queued"
    return (
        f"{action} ingest for {ticker} {form_type} FY{fiscal_year}. "
        f"job_id={actual_job_id}"
    )


async def handle_check_ingest_status(args: dict, session: AsyncSession) -> str:
    job_id = str(args.get("job_id", "")).strip()
    if not job_id:
        return "Error: 'job_id' is required."

    wait = bool(args.get("wait", False))
    deadline = asyncio.get_event_loop().time() + _WAIT_TIMEOUT

    while True:
        result = await session.execute(
            select(IngestJob)
            .where(IngestJob.job_id == job_id)
            .execution_options(populate_existing=True)
        )
        job = result.scalar_one_or_none()

        if job is None:
            return f"No ingest job found with job_id={job_id!r}."

        if job.status in ("done", "failed") or not wait:
            if job.status == "done":
                return (
                    f"Ingest complete: {job.ticker} {job.form_type} FY{job.fiscal_year}. "
                    "The filing is ready to search."
                )
            if job.status == "failed":
                return (
                    f"Ingest failed for {job.ticker} {job.form_type} FY{job.fiscal_year}: "
                    f"{job.error_message or 'unknown error'}. "
                    "You can retry with ingest_filing."
                )
            display = "in progress" if job.status in ("queued", "running") else job.status
            return (
                f"Ingest for {job.ticker} {job.form_type} FY{job.fiscal_year} "
                f"is {display} (job_id={job_id})."
            )

        if asyncio.get_event_loop().time() >= deadline:
            return (
                f"Timed out waiting for ingest of {job.ticker} {job.form_type} "
                f"FY{job.fiscal_year}. Job is still {job.status}. "
                "Try check_ingest_status again later."
            )

        await asyncio.sleep(_POLL_INTERVAL)


async def dispatch(
    tool_name: str,
    args: dict,
    session: AsyncSession,
    chunk_accumulator: list[ChunkResult],
    chunk_offset: int,
    conversation_id: int | None = None,
    arq_redis=None,
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

    if tool_name == "list_companies":
        return await handle_list_companies(session)

    if tool_name == "list_filings":
        return await handle_list_filings(args, session)

    if tool_name == "ingest_filing":
        return await handle_ingest_filing(args, session, arq_redis, conversation_id)

    if tool_name == "check_ingest_status":
        return await handle_check_ingest_status(args, session)

    if tool_name == "get_filing":
        return await handle_get_filing(args, session)

    raise ValueError(f"Unknown tool '{tool_name}'.")
