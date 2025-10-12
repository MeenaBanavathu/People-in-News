# app/models.py
from sqlalchemy import (
    Integer, String, Text, DateTime, Boolean, ForeignKey, Index
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from database import Base

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class Person(Base, TimestampMixin):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Person's canonical name (unique)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Backrefs
    person_articles = relationship("PersonArticle", back_populates="person", cascade="all, delete-orphan")

class Article(Base, TimestampMixin):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # A short catchy title generated for UI
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)  # Avoid duplicates
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Backrefs
    person_articles = relationship("PersonArticle", back_populates="article", cascade="all, delete-orphan")

    # Helpful index for queries by recency
    __table_args__ = (
        Index("idx_articles_published_at", "published_at"),
    )

class PersonArticle(Base):
    __tablename__ = "person_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    person = relationship("Person", back_populates="person_articles")
    article = relationship("Article", back_populates="person_articles")
