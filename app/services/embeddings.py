"""
Embedding service for retrieval.

The configured fastembed model is loaded lazily and kept warm after the first
call. For E5-family models, retrieval quality depends on using "query:" and
"passage:" prefixes, so this wrapper centralizes that behavior.
"""

import logging
from typing import Literal

from fastembed import TextEmbedding

from app.config import settings

logger = logging.getLogger(__name__)

EmbeddingInputType = Literal["query", "passage"]

_model: TextEmbedding | None = None


def get_model() -> TextEmbedding:
    global _model
    if _model is None:
        logger.info("Loading embedding model: %s", settings.embedding_model)
        _model = TextEmbedding(model_name=settings.embedding_model)
        logger.info("Embedding model loaded")
    return _model


def _prepare_text(text: str, input_type: EmbeddingInputType) -> str:
    normalized = " ".join(text.split())
    model_name = settings.embedding_model.lower()
    if "e5" in model_name:
        prefix = "query" if input_type == "query" else "passage"
        return f"{prefix}: {normalized}"
    return normalized


def embed_texts(
    texts: list[str],
    input_type: EmbeddingInputType = "passage",
) -> list[list[float]]:
    """Embed multiple texts as query or passage vectors."""
    if not texts:
        return []

    model = get_model()
    prepared = [_prepare_text(text, input_type) for text in texts]
    embeddings = list(model.embed(prepared))
    vectors = [vec.tolist() for vec in embeddings]

    for vector in vectors:
        if len(vector) != settings.embedding_dimensions:
            raise ValueError(
                "Embedding dimension mismatch: "
                f"expected {settings.embedding_dimensions}, got {len(vector)}"
            )

    return vectors


def embed_text(text: str, input_type: EmbeddingInputType = "query") -> list[float]:
    """Embed a single text as a query vector by default."""
    return embed_texts([text], input_type=input_type)[0]
