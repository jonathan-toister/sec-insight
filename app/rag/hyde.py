"""HyDE — Hypothetical Document Embeddings.

Instead of embedding the user's question directly, we ask Claude to write a
short passage in SEC filing language that *would* answer the question, then
embed that passage. This aligns the query embedding with document-space rather
than question-space, significantly improving cosine similarity against real
10-K/10-Q text.
"""
import logging

import anthropic

from app.config import settings

_logger = logging.getLogger(__name__)

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

_SYSTEM_PROMPT = """\
You are a financial document writer. Your task is to write a short passage that \
would plausibly appear in a U.S. SEC filing (10-K annual report or 10-Q quarterly \
report) as the answer to an investor's question.

Write in formal financial disclosure language. Use specific financial terminology \
and reference GAAP accounting concepts where relevant. Include plausible but \
clearly generic figures (e.g. "$X million", "approximately $1.2 billion") where \
the question calls for numbers — do NOT invent real company names or specific \
real figures.

The passage should be 3–5 sentences, written as if excerpted from a real filing's \
Management Discussion & Analysis or Risk Factors section. Output only the passage \
itself — no headers, prefixes, or meta-commentary.\
"""

_USER_TEMPLATE = "Investor question: {question}\n\nWrite the hypothetical filing passage that would answer this question."


async def generate_hypothetical_document(question: str) -> str:
    """
    Generate a hypothetical SEC filing passage for the given investor question.
    The returned text is embedded (not the raw question) to improve retrieval
    against financial filing text.
    """
    message = await _client.messages.create(
        model=settings.hyde_model,
        max_tokens=200,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _USER_TEMPLATE.format(question=question)}],
    )
    u = message.usage
    _logger.info(
        "token_usage label=hyde model=%s input=%d output=%d",
        message.model,
        u.input_tokens,
        u.output_tokens,
    )
    return message.content[0].text.strip()
