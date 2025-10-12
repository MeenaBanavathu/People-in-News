from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from dotenv import load_dotenv, find_dotenv
from sqlalchemy.orm import Session
from sqlalchemy import select, desc, func, delete, text
import httpx
import asyncio
import os
import json
from image_fetch import generate_person_image


from database import get_db, engine, Base
import crud, models, schemas

app = FastAPI(title="NewsFaces API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database simulation (replace with actual DB later)
news_cards_db = []

# Configuration

def config() -> tuple[str, str]:
    # Load .env if present. override=False so real env vars win in prod.
    load_dotenv(find_dotenv(), override=False)

    news = os.getenv("NEWS_API_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")
    google_key = os.getenv("GOOGLE_API_KEY", "")
    google_cse = os.getenv("GOOGLE_CSE_ID", "")

    missing = [name for name, val in [("NEWS_API_KEY", news), ("GROQ_API_KEY", groq_key), ("GOOGLE_API_KEY", google_key), ("GOOGLE_CSE_ID", google_cse)] if not val]
    if missing:
        raise RuntimeError(f"Missing env var(s): {', '.join(missing)}")

    return news, groq_key, google_key, google_cse


class NewsCard(BaseModel):
    id: str
    name: str
    image_url: str
    catchy_title: str
    summary: str
    link: str
    published_at: str
    
async def fetch_news_articles():
    url = "https://newsapi.org/v2/top-headlines"
    params = {
        "apiKey": config()[0], 
        "country": "us",
        "language": "en",
        "pageSize": 100,
        
        }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json().get("articles", [])


async def extract_people_and_generate_content(article: dict):
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        raise RuntimeError("GROQ_API_KEY not set")

    system_prompt = (
    "You are an information extractor for a people-focused news feed.\n"
    "\n"
    "Task:\n"
    "- Read the article title, description and full content text.\n"
    "- Identify the person or people the article is PRIMARILY about (the central subject[s]).\n"
    "- Use only explicitly named individuals; ignore authors/bylines and generic groups (e.g., 'officials', 'police', 'committee').\n"
    "- EXCLUDE any article whose main subject is not a person but about animals, companies, products, laws, teams, places, disasters, studies, discoveries, fossils.\n"
    "- If multiple people are equally central of the subject, include all of them by joining their full names with ',' in the name field.\n"
    "- INCLUDE articles where the article's title clearly centers on a person’s action/status/statement.\n"
    "- name should be the Full name of the main person(s), not just the first name or last name the article is about, do not include generic groups.\n"
    "Output rules:\n"
    "- If NO qualifying person is present, do not include the article in the final output.\n"
    "- Otherwise return STRICT JSON with keys: name, catchy_title, summary.\n"
    "\n"
    "Style & constraints:\n"
    "- name is the full name of the main person(s) the article is about.\n"
    "- catchy_title should be less than 4 words, no emojis or quotes.\n"
    "- summary is neutral, factual, 2–3 sentences.\n"
    "- Output JSON ONLY, no extra text."
 )


    user_content = (
        f"Title: {article.get('title', '')}\n"
        f"Text: {(article.get('description') or '')} {(article.get('content') or '')}"
    )

    payload = {
        "model": "llama-3.1-8b-instant",              # Groq model
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"}     # enforce JSON
    }

    headers = {
        "Authorization": f"Bearer {groq_key}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(base_url="https://api.groq.com/openai/v1", timeout=30) as client:
        r = await client.post("/chat/completions", json=payload, headers=headers)
        if r.status_code != 200:
            return None

    try:
        content = r.json()["choices"][0]["message"]["content"].strip()
        obj = json.loads(content) 
       
    except Exception as e:
        print("[Groq] JSON parse error:", e, "content:", content[:300] if 'content' in locals() else "")
        return None

    # Normalize & enforce constraints
    name = (obj.get("name") or "").strip()
    catchy = (obj.get("catchy_title") or "").strip()
    summary = (obj.get("summary") or "").strip()

    if not name:
        return None

    if len(catchy.split()) > 5:
        catchy = " ".join(catchy.split()[:5])

    return {"name": name, "catchy_title": catchy, "summary": summary}       

#async def generate_person_image(person_name: str) -> str:
    """
    Fetch a face image for the person via Google Programmable Search.
    Falls back to a neutral initials avatar if nothing found.
    """
    # if not config()[2] or not config()[3]:
    #     # Safe fallback if keys are missing
    #     return f"https://ui-avatars.com/api/?name={person_name.replace(' ', '+')}&size=400&background=random"

    # params = {
    #     "key": config()[2],
    #     "cx": config()[3],
    #     "q": person_name,
    #     "searchType": "image",
    #     "imgType": "face",      # bias toward faces
    #     "safe": "active",
    #     "num": 1,               # try a few; we’ll pick the first viable
    # }

    # Uncomment when rate limit is fixed
    # try:
    #     async with httpx.AsyncClient(timeout=20) as client:
    #         r = await client.get("https://www.googleapis.com/customsearch/v1", params=params)
    #         r.raise_for_status()
    #         items = r.json().get("items", []) or []
    #         print(items)
    #         # Pick the first reasonably-sized image
    #         for it in items:
    #             url = it.get("link")
    #             if isinstance(url, str) and url.startswith("http"):
    #                 return url
    # except Exception as e:
    #     print("[Google CSE] image fetch error:", e)

    # Final fallback

    #return f"https://ui-avatars.com/api/?name={person_name.replace(' ', '+')}&size=400&background=random"


async def process_news_pipeline():
    """Main pipeline to process news and generate cards"""
    global news_cards_db
    
    print("🔄 Fetching news articles...")
    articles = await fetch_news_articles()
    print(f"🗞️ Fetched {len(articles)} articles")
    
    new_cards = []
    
    for idx, article in enumerate(articles):  
        try:
            print(f"📰 Processing article {idx + 1}: {article['title']}")
            
            # Extract people and generate content
            ai_content = await extract_people_and_generate_content(article)
            
            if not ai_content:
                print(f"no person found in article {idx + 1}, skipping...")
                continue
            
            # Generate image
            for name in ai_content['name'].split(","):
                name = name.strip()
                if not name:
                    continue
                image_url = await generate_person_image(name)

                print(f"🎨 Generating image for {ai_content['name']}, {image_url}")
                ai_content['name'] = name  # use individual name for the card
                ai_content['image_url'] = image_url
                
                # Create card
                card = NewsCard(
                    id=str(len(new_cards) + 1),
                    name=ai_content['name'],
                    image_url=image_url,
                    catchy_title=ai_content['catchy_title'],
                    summary=ai_content['summary'],
                    link=article['url'],
                    published_at=article['publishedAt']
                )
                
                new_cards.append(card.dict())
                print(f"✅ Card created for {ai_content['name']}, {card}")
            
        except Exception as e:
            print(f"❌ Error processing article: {str(e)}")
            continue
    
    news_cards_db = new_cards
    print(f"✨ Pipeline complete! Generated {len(new_cards)} cards")

# utils: run pipeline, then ingest what was produced
async def run_pipeline_and_ingest():
    await process_news_pipeline()  # fills global news_cards_db with dicts
    db = next(get_db())
    try:
        # Convert dicts -> Pydantic models expected by ingest_cards
        cards_models = [schemas.NewsCard(**c) for c in news_cards_db]
        if cards_models:
            ingest_cards_internal(cards_models, db)
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    # run end-to-end in background on startup
    asyncio.create_task(run_pipeline_and_ingest())

    
    

@app.get("/api/people-news", response_model=List[NewsCard])
async def get_people_news():
    """Get all news cards"""
    return news_cards_db

@app.post("/api/refresh-news")
async def refresh_news(background_tasks: BackgroundTasks):
    """Manually trigger news refresh"""
    background_tasks.add_task(process_news_pipeline)
    return {"message": "News refresh started"}

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "cards_count": len(news_cards_db),
        "timestamp": datetime.now().isoformat()
    }


# --- Create tables on startup (dev only; use Alembic migrations in prod) ---
@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)

# --- Health/Root ---
@app.get("/", tags=["meta"])
def health():
    return {"ok": True, "service": "people-in-news", "version": "1.0.0"}

# --- Ingest your existing cards array ---
# @app.post("/ingest/cards", response_model=dict, tags=["ingest"])
def ingest_cards_internal(cards: List[schemas.NewsCard], db: Session) -> dict:
    if not cards:
        raise HTTPException(status_code=400, detail="No cards provided.")
    count = crud.ingest_newscards(db, cards)
    return {"ingested": count}

# --- List people (optionally filter by name) ---
@app.get("/people", response_model=List[schemas.PersonResponse], tags=["people"])
def get_people(
    limit: int = Query(100, ge=1, le=500),
    q: Optional[str] = Query(None, description="Filter by person name (contains, case-insensitive)"),
    db: Session = Depends(get_db),
):
    stmt = select(models.Person).order_by(desc(models.Person.created_at)).limit(limit)
    if q:
        # Case-insensitive contains (SQLite LIKE is case-insensitive by default; ok for dev)
        stmt = select(models.Person).where(models.Person.name.ilike(f"%{q}%")).order_by(desc(models.Person.created_at)).limit(limit)
    people = db.execute(stmt).scalars().all()
    return people

# --- Get "cards" view: people with their top-N articles ---
@app.get("/people/cards", response_model=List[schemas.PersonNewsCard], tags=["people"])
def get_people_cards(top: int = Query(3, ge=1, le=10), db: Session = Depends(get_db)):
    p = models.Person
    a = models.Article
    pa = models.PersonArticle

    # row_number() over each person’s articles by newest published_at
    rn = func.row_number().over(
        partition_by=pa.person_id,
        order_by=(a.published_at.desc().nullslast(), a.created_at.desc())
    )

    subq = (
        select(
            p.id.label("person_id"),
            p.name.label("person_name"),
            a.id.label("article_id"),
            a.title,
            a.summary,
            a.link,
            p.image_url,
            a.published_at,
            rn.label("rn"),
        )
        .select_from(p)
        .join(pa, pa.person_id == p.id)
        .join(a, a.id == pa.article_id)
        .order_by(p.id, a.published_at.desc().nullslast(), a.created_at.desc())
    ).subquery()

    # keep only top-N per person
    topq = select(subq).where(subq.c.rn <= top)
    rows = db.execute(topq).all()

    # group rows → cards
    cards = {}
    for r in rows:
        pid = r.person_id
        if pid not in cards:
            cards[pid] = {
                "id": pid,
                "name": r.person_name,
                "articles": [],
            }
        cards[pid]["articles"].append({
            "id": r.article_id,
            "title": r.title,
            "summary": r.summary,
            "link": r.link,
            "image_url": r.image_url,
            "published_at": r.published_at.isoformat() if r.published_at else None,
        })

    # optional: sort people by their latest article’s published_at desc
    def latest_pub(card):
        first = card["articles"][0]["published_at"] if card["articles"] else None
        return first or ""
    ordered = sorted(cards.values(), key=latest_pub, reverse=True)

    return ordered

# --- Get a single person by id ---
@app.get("/people/{person_id}", response_model=schemas.PersonResponse, tags=["people"])
def get_person(person_id: int, db: Session = Depends(get_db)):
    person = db.get(models.Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    return person

# --- Articles for a given person ---
@app.get("/people/{person_id}/articles", response_model=List[schemas.ArticleResponse], tags=["articles"])
def get_person_articles(
    person_id: int,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    # Reuse the CRUD helper
    if not db.get(models.Person, person_id):
        raise HTTPException(status_code=404, detail="Person not found")
    articles = crud.list_articles_for_person(db, person_id, limit=limit)
    return articles

# --- Latest articles across everyone (for a "feed") ---
@app.get("/articles/latest", response_model=List[schemas.ArticleResponse], tags=["articles"])
def get_latest_articles(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    stmt = (
        select(models.Article)
        .order_by(models.Article.published_at.desc().nullslast(), models.Article.created_at.desc())
        .limit(limit)
    )
    articles = db.execute(stmt).scalars().all()
    return articles

# --- Lookup article by link (useful to check if present) ---
@app.get("/articles/by-link", response_model=schemas.ArticleResponse, tags=["articles"])
def get_article_by_link(link: str = Query(..., min_length=5), db: Session = Depends(get_db)):
    stmt = select(models.Article).where(models.Article.link == link).limit(1)
    article = db.execute(stmt).scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@app.get("/debug/clear-db")  # not recommended; enable only if you must
def clear_db(db=Depends(get_db)):
    db.execute(text("DELETE FROM person_articles;"))
    db.execute(text("DELETE FROM articles;"))
    db.execute(text("DELETE FROM people;"))
    db.commit()
    return {"ok": True}