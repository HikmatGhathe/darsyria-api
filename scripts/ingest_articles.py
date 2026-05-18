"""
Ingest markdown article files into the database with embeddings.

Run from the darsyria-api root:
    python -m scripts.ingest_articles

The script is idempotent: re-running it replaces articles with the same slug.
"""

import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models.article import Article, ArticleChunk
from app.services.embeddings import embed_texts


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MAX_CHARS_PER_CHUNK = 1500
OVERLAP_CHARS = 200


def articles_dir() -> Path:
    configured = Path(settings.article_source_dir)
    if configured.is_absolute():
        return configured
    return Path(__file__).parent.parent / configured


def parse_markdown(file_path: Path) -> tuple[str, str | None, str]:
    """Extract title, optional last-reviewed date, and body from a markdown file."""
    content = file_path.read_text(encoding="utf-8")

    title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
    if not title_match:
        raise ValueError(f"{file_path.name}: no '# Title' heading found")
    title = title_match.group(1).strip()

    reviewed_match = re.search(
        r"\*Last reviewed:\s*(\d{1,2}\s+\w+\s+\d{4})",
        content,
        re.IGNORECASE,
    )
    last_reviewed = reviewed_match.group(1) if reviewed_match else None

    return title, last_reviewed, content


def split_into_chunks(text: str) -> list[tuple[str, str | None]]:
    """
    Split text into chunks while trying to preserve markdown section boundaries.
    Returns (chunk_text, section_heading) pairs.
    """
    sections = re.compile(r"\n(?=##+\s)").split(text)
    chunks: list[tuple[str, str | None]] = []

    for section in sections:
        section = section.strip()
        if not section:
            continue

        heading_match = re.match(r"^(##+\s.+?)$", section, re.MULTILINE)
        section_name = (
            heading_match.group(1).strip("#").strip() if heading_match else None
        )

        if len(section) <= MAX_CHARS_PER_CHUNK:
            chunks.append((section, section_name))
            continue

        start = 0
        while start < len(section):
            end = min(start + MAX_CHARS_PER_CHUNK, len(section))
            chunk = section[start:end]

            if end < len(section):
                last_period = chunk.rfind(". ")
                last_paragraph = chunk.rfind("\n\n")
                break_at = max(last_period, last_paragraph)
                if break_at > MAX_CHARS_PER_CHUNK - 400:
                    chunk = chunk[: break_at + 1]
                    end = start + len(chunk)

            chunk = chunk.strip()
            if chunk:
                chunks.append((chunk, section_name))

            if end >= len(section):
                break

            next_start = end - OVERLAP_CHARS
            start = next_start if next_start > start else end

    return chunks


def parse_last_reviewed(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d %B %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        logger.warning("Could not parse last-reviewed date: %s", value)
        return None


def ingest_file(file_path: Path) -> None:
    slug = file_path.stem
    logger.info("Ingesting %s", slug)

    title, last_reviewed_str, body = parse_markdown(file_path)
    chunks = split_into_chunks(body)
    logger.info("%s: %d chunks", slug, len(chunks))

    chunk_texts = [content for content, _section in chunks]
    embeddings = embed_texts(chunk_texts, input_type="passage")
    logger.info("%s: embeddings generated", slug)

    db = SessionLocal()
    try:
        existing = db.execute(
            select(Article).where(Article.slug == slug)
        ).scalar_one_or_none()
        if existing:
            db.delete(existing)
            db.commit()
            logger.info("%s: replaced existing article", slug)

        article = Article(
            slug=slug,
            locale="en",
            title=title,
            body=body,
            last_reviewed_at=parse_last_reviewed(last_reviewed_str),
            source_file=file_path.name,
        )
        db.add(article)
        db.flush()

        for position, ((content, section), embedding) in enumerate(
            zip(chunks, embeddings, strict=True)
        ):
            db.add(
                ArticleChunk(
                    article_id=article.id,
                    position=position,
                    content=content,
                    embedding=embedding,
                    section=section,
                )
            )

        db.commit()
        logger.info("%s: saved article and %d chunks", slug, len(chunks))
    finally:
        db.close()


def main() -> None:
    source_dir = articles_dir()
    if not source_dir.exists():
        logger.error("Articles directory not found: %s", source_dir)
        sys.exit(1)

    md_files = sorted(source_dir.glob("*.md"))
    if not md_files:
        logger.error("No markdown files found in %s", source_dir)
        sys.exit(1)

    logger.info("Found %d articles to ingest in %s", len(md_files), source_dir)
    for file_path in md_files:
        try:
            ingest_file(file_path)
        except Exception:
            logger.exception("Failed to ingest %s", file_path.name)

    logger.info("Ingestion complete")


if __name__ == "__main__":
    main()
