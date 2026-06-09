"""Embeddings via OpenAI (text-embedding-3-small, 1536 dims)."""
from openai import AsyncOpenAI

from app.config import settings

_client = AsyncOpenAI(api_key=settings.openai_api_key)

_BATCH_SIZE = 512
_MAX_CHARS = 30_000  # ~7500 tokens — safely under OpenAI's 8192 token limit


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts using OpenAI text-embedding-3-small.
    Returns vectors in the same order as the input.
    Called at ingest time (many chunks) and query time (one HyDE document).
    """
    if not texts:
        return []

    # Truncate before sending — OpenAI rejects inputs over 8192 tokens
    texts = [t[:_MAX_CHARS] for t in texts]

    results: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        response = await _client.embeddings.create(
            model=settings.embedding_model,
            input=batch,
        )
        batch_vectors = [
            item.embedding for item in sorted(response.data, key=lambda x: x.index)
        ]
        results.extend(batch_vectors)

    return results
