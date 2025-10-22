#crud.py
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from datetime import datetime
import models
import schemas  
from typing import Iterable

def _canon(s: str) -> str:
    return " ".join((s or "").strip().lower().split())

def get_or_create_person(db: Session, name: str, image_url: str) -> models.Person:
    name_ci = _canon(name)
    if not name_ci:
        return None
    
    existing = (
        db.query(models.Person)
        .filter(func.lower(models.Person.name) == name_ci)
        .first()
    )

    if existing:
        if image_url and not existing.image_url:
            existing.image_url = image_url
        return existing

    display = " ".join(w.capitalize() for w in name.strip().split())
    person = models.Person(name=display, image_url=image_url)
    db.add(person)
    db.flush()  
    return person

# ---- Article helpers ----
def get_or_create_article(
    db: Session,
    *,
    title: str,
    summary: str, 
    link: str, 
    published_at: datetime | None, 
    source_name: str | None = None
    ) -> models.Article:
    stmt = select(models.Article).where(models.Article.link == link)
    art = db.execute(stmt).scalar_one_or_none()
    if art:
        if not art.published_at and published_at:
            art.published_at = published_at
        if not art.source_name and source_name:
            art.source_name = source_name
        if title and art.title != title:
            art.title = title
        if summary and art.summary != summary:
            art.summary = summary
        return art
    art = models.Article(
        title=title, 
        summary=summary, 
        link=link, 
        published_at=published_at, 
        source_name=source_name
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

def ingest_newscards(db: Session, cards: Iterable[schemas.NewsCard]) -> int:
    count = 0
    for c in cards:
        # Interpret NewsCard fields
        person_name = (c.name or "").strip()
        person_img = c.image_url 
        title = c.catchy_title or c.name
        summary = c.summary or ""
        link = c.link

        published_at = None
        if getattr(c, "published_at", None):
            try:
                published_at = datetime.fromisoformat(c.published_at.replace("Z", "+00:00"))
            except Exception:
                published_at = None

        person = get_or_create_person(db, person_name, person_img)
        article = get_or_create_article(
            db, title=title, summary=summary, link=link, published_at=published_at
        )
        if person is not None:                                    
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
