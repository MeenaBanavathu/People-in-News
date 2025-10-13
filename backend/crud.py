#crud.py
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime
import models
import schemas  
from typing import Iterable

# ---- Person helpers ----
def get_or_create_person(db: Session, name: str, image_url: str | None = None) -> models.Person:
    stmt = select(models.Person).where(models.Person.name == name)
    person = db.execute(stmt).scalar_one_or_none()
    if person:
        # Optionally update image_url if blank
        if image_url and not person.image_url:
            person.image_url = image_url
        return person
    person = models.Person(name=name, image_url=image_url)
    db.add(person)
    db.flush()  # get ID
    return person

# ---- Article helpers ----
def get_or_create_article(
    db: Session, *, title: str, summary: str, link: str, published_at: datetime | None,
    image_url: str | None = None, source_name: str | None = None
) -> models.Article:
    stmt = select(models.Article).where(models.Article.link == link)
    art = db.execute(stmt).scalar_one_or_none()
    if art:
        # Light updates for newer info
        if not art.published_at and published_at:
            art.published_at = published_at
        if not art.image_url and image_url:
            art.image_url = image_url
        if not art.source_name and source_name:
            art.source_name = source_name
        if title and art.title != title:
            art.title = title
        if summary and art.summary != summary:
            art.summary = summary
        return art
    art = models.Article(
        title=title, summary=summary, link=link, published_at=published_at,
        image_url=image_url, source_name=source_name
    )
    db.add(art)
    db.flush()
    return art

def link_person_article(db: Session, person: models.Person, article: models.Article, is_primary: bool = True):
    # Avoid duplicates by checking current relationships (DB has a unique constraint if you add one)
    for pa in article.person_articles:
        if pa.person_id == person.id:
            return pa
    pa = models.PersonArticle(person_id=person.id, article_id=article.id, is_primary=is_primary)
    db.add(pa)
    return pa

# ---- Bulk ingest for NewsCard list ----
def ingest_newscards(db: Session, cards: Iterable[schemas.NewsCard]) -> int:
    count = 0
    for c in cards:
        # Interpret NewsCard fields
        person_name = c.name.strip()
        person_img = getattr(c, "image_url", None)
        title = c.catchy_title or c.name
        summary = c.summary or ""
        link = c.link

        published_at = None
        if getattr(c, "published_at", None):
            try:
                # Accept "2025-10-10T13:28:17Z" or with offset
                published_at = datetime.fromisoformat(c.published_at.replace("Z", "+00:00"))
            except Exception:
                published_at = None

        person = get_or_create_person(db, person_name, person_img)
        article = get_or_create_article(
            db, title=title, summary=summary, link=link, published_at=published_at, image_url=person_img
        )
        link_person_article(db, person, article, is_primary=True)
        count += 1
    db.commit()
    return count

# ---- Query helpers ----
def list_people(db: Session, limit: int = 50):
    stmt = select(models.Person).order_by(models.Person.created_at.desc()).limit(limit)
    return db.execute(stmt).scalars().all()

def list_articles_for_person(db: Session, person_id: int, limit: int = 50):
    stmt = (
        select(models.Article)
        .join(models.PersonArticle, models.PersonArticle.article_id == models.Article.id)
        .where(models.PersonArticle.person_id == person_id)
        .order_by(models.Article.published_at.desc().nullslast())
        .limit(limit)
    )
    return db.execute(stmt).scalars().all()
