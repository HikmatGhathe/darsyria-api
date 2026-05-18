from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article import Article, ArticleChunk
from app.services.embeddings import embed_text


@dataclass(frozen=True)
class RetrievedChunk:
    slug: str
    title: str
    locale: str
    section: str | None
    content: str
    distance: float


def retrieve_article_chunks(
    db: Session,
    query: str,
    locale: str = "en",
    limit: int = 3,
) -> list[RetrievedChunk]:
    """Retrieve the most similar article chunks for a user query."""
    query_embedding = embed_text(query, input_type="query")
    distance = ArticleChunk.embedding.cosine_distance(query_embedding).label("distance")
    locales = {locale, "en"}

    rows = db.execute(
        select(
            Article.slug,
            Article.title,
            Article.locale,
            ArticleChunk.section,
            ArticleChunk.content,
            distance,
        )
        .join(Article, Article.id == ArticleChunk.article_id)
        .where(Article.locale.in_(locales))
        .order_by(distance)
        .limit(limit)
    ).all()

    return [
        RetrievedChunk(
            slug=slug,
            title=title,
            locale=article_locale,
            section=section,
            content=content,
            distance=float(chunk_distance),
        )
        for slug, title, article_locale, section, content, chunk_distance in rows
    ]


def format_retrieval_context(chunks: list[RetrievedChunk]) -> str:
    """Format retrieved chunks for the LLM system prompt."""
    if not chunks:
        return ""

    parts = []
    for index, chunk in enumerate(chunks, start=1):
        section = f", section: {chunk.section}" if chunk.section else ""
        parts.append(
            "\n".join(
                [
                    f"[Source {index}: {chunk.slug}{section}]",
                    f"Title: {chunk.title}",
                    chunk.content,
                ]
            )
        )

    return "\n\n---\n\n".join(parts)
