import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.config import settings
from app.database import Base


EMBEDDING_DIM = settings.embedding_dimensions


class Article(Base):
    __tablename__ = "articles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Stable identifier matching the source filename, e.g. "03-reciprocity".
    slug = Column(String(100), nullable=False, unique=True, index=True)
    locale = Column(String(5), nullable=False, default="en")

    title = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)

    last_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    source_file = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<Article slug={self.slug} locale={self.locale}>"


class ArticleChunk(Base):
    __tablename__ = "article_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    article_id = Column(
        UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    section = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index(
    "ix_article_chunks_embedding",
    ArticleChunk.embedding,
    postgresql_using="ivfflat",
    postgresql_with={"lists": 100},
    postgresql_ops={"embedding": "vector_cosine_ops"},
)
