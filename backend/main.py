from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, JSONResponse
from typing import List, Optional, Set
from datetime import datetime
from dotenv import load_dotenv, find_dotenv
from sqlalchemy.orm import Session
from sqlalchemy import select, desc, func, text
import httpx
import asyncio
import os
import json
import time
from contextlib import suppress

from image_fetch import generate_person_image
from validators import is_valid_person_name
from database import get_db, engine, Base
import crud, models, schemas

app = FastAPI(title="NewsFaces API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173",
                   "http://127.0.0.1:5173",
                   ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

news_cards_db = []

_run_lock = asyncio.Lock()
_update_task: asyncio.Task | None = None
_subscribers: Set[asyncio.Queue[str]] = set()

# Configuration

def config() -> tuple[str, str]:
    # Load .env if present. override=False so real env vars win in prod.
    load_dotenv(find_dotenv(), override=False)

    news = os.getenv("NEWS_API_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")
    REFRESH_INTERVAL_MIN = int(os.getenv("NEWS_REFRESH_INTERVAL_MIN", "10"))    
    SSE_HEARTBEAT_SEC = int(os.getenv("SSE_HEARTBEAT_SEC", "30"))

    missing = [name for name, val in [("NEWS_API_KEY", news), ("GROQ_API_KEY", groq_key)] if not val]
    if missing:
        raise RuntimeError(f"Missing env var(s): {', '.join(missing)}")

    return news, groq_key


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
    "- Extract their FULL, PROPER NAMES using your knowledge.\n"
    "\n"
    "NAME EXTRACTION RULES:\n"
    "- If article mentions 'Trump', output 'Donald Trump' (use full name)\n"
    "- If article mentions 'Biden', output 'Joe Biden'\n"
    "- If article mentions 'Modi', output 'Narendra Modi'\n"
    "- Use your knowledge to expand partial names (last name only or first name only) to complete names\n"
    "- For mononyms (people known by single name), use that single name: 'Madonna', 'Nani', 'Cher', 'Pele'\n"
    "- For names with titles, extract only the name: 'Benjamin Netanyahu' not 'PM Netanyahu'\n"
    "- If a person is mentioned multiple times with variations, consolidate to ONE full name\n"
    "- If multiple people are equally central subjects, list ALL full names separated by commas\n"
    "- If you cannot determine the full name or the person is truly unknown, skip the article\n"
    "\n"
    "STRICT EXCLUSION RULES - Do NOT include:\n"
    "- Organizations, militias, or groups (e.g., 'Hamas', 'Taliban', 'US Army', 'FBI', 'police', 'committee')\n"
    "- Job titles or roles without names (e.g., 'President', 'CEO', 'officials', 'spokesperson')\n"
    "- Generic references (e.g., 'unknown', 'three men', 'a woman', 'suspects', 'victim', 'unidentified person')\n"
    "- Nationalities or demographics (e.g., 'Americans', 'youth', 'citizens')\n"
    "- Animals, companies, products, laws, teams, places, disasters, studies, discoveries, fossils, fictional characters\n"
    "- Authors, bylines, or reporters (focus only on subjects of the article)\n"
    "\n"
    "INCLUDE articles where:\n"
    "- The title/content clearly centers on a specific named person's action, status, or statement\n"
    "- A named individual is the primary subject being discussed\n"
    "\n"
    "EXCLUDE articles where:\n"
    "- NO specific person is identified as the main subject\n"
    "- Only organizations, groups, or unnamed individuals are the focus\n"
    "- The person cannot be identified with a proper name\n"
    "\n"
    "Output rules:\n"
    "- If NO qualifying person is present, return null or empty response (do not fabricate output)\n"
    "- Otherwise return STRICT JSON with keys: name, catchy_title, summary\n"
    "\n"
    "Style & constraints:\n"
    "- name: Full proper name(s), comma-separated if multiple people. Use knowledge to expand partial names. Cannot be null, cannot be a group/organization.\n"
    "- catchy_title: Less than 4 words, no emojis, no quotes, person-focused\n"
    "- summary: Neutral, factual, 2–3 sentences about what the person did/said/experienced\n"
    "\n"
    "Output ONLY valid JSON, no extra text or explanation."
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

    # if len(catchy.split()) > 5:
    #     catchy = " ".join(catchy.split()[:5])

    return {"name": name, "catchy_title": catchy, "summary": summary}       

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
            print(f"Extracted content: {ai_content}")
            if not ai_content:
                print(f"no person found in article {idx + 1}, skipping...")
                continue
            
            # Generate image
            for name in ai_content['name'].split(","):
                name = name.strip()
                if not name:
                    continue
                if not is_valid_person_name(name):
                    print(f"🚫 Invalid person name '{name}' in article {idx + 1}, skipping...")
                    continue    
                
                image_url = await generate_person_image(name)

                print(f"🎨 Generating image for {name}, {image_url}")
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
                print(f"✅ Card created for {ai_content['name']}")
            
        except Exception as e:
            print(f"❌ Error processing article: {str(e)}")
            continue
    
    news_cards_db = new_cards
    print(f"✨ Pipeline complete! Generated {len(new_cards)} cards")


async def run_pipeline_and_ingest():
    await process_news_pipeline()  
    db = next(get_db())
    try:
        cards_models = [schemas.NewsCard(**c) for c in news_cards_db]
        if cards_models:
            ingest_cards_internal(cards_models, db)
    finally:
        db.close()

async def _notify_update(payload: dict):
    msg = json.dumps(payload, ensure_ascii=False)
    dead = []
    for q in list(_subscribers):
        try:
            await q.put(msg)
        except Exception:
            dead.append(q)
    for q in dead:
        _subscribers.discard(q)

async def _sse_event_stream(request: Request, q: asyncio.Queue[str]):
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30)
                yield f"event: news_update\ndata: {msg}\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        _subscribers.discard(q)

@app.get("/events")
async def events(request: Request):
    #SSE endpoint for real-time updates
    q: asyncio.Queue[str] = asyncio.Queue()
    _subscribers.add(q)
    return StreamingResponse(_sse_event_stream(request, q), media_type="text/event-stream")

async def periodic_refresh():
    await asyncio.sleep(10 * 60)
    while True:
        try:
            async with _run_lock:
                print("🔄 Starting periodic news refresh...")
                await run_pipeline_and_ingest()
                await _notify_update({"kind": "news_update", "ts": time.time()})
                print("✅ News refresh complete.")
        except Exception as e:
            print("❌ Error during periodic refresh:", e)
        await asyncio.sleep(10 * 60)



@app.get("/api/people-news", response_model=List[NewsCard])
async def get_people_news():
    """Get all news cards"""
    return news_cards_db

@app.post("/api/refresh-news")
async def refresh_news():
    """
    Manually trigger a full run (pipeline + ingest) safely.
    """
    if _run_lock.locked():
        return JSONResponse({"status": "busy"}, status_code=409)
    async with _run_lock:
        await run_pipeline_and_ingest()
        await _notify_update({"kind": "news_update", "ts": time.time()})
    return {"status": "ok", "cards": len(news_cards_db)}

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "cards_count": len(news_cards_db),
        "timestamp": datetime.now().isoformat()
    }

@app.on_event("startup")
async def on_startup():
    global _update_task
    try:
        async with _run_lock:
            await run_pipeline_and_ingest()
            await _notify_update({"kind": "news_update", "ts": time.time()})
    except Exception as e:
        print("❌ Error during startup initial run:", e)
    _update_task = asyncio.create_task(periodic_refresh())
    print("[startup] periodic refresh every 10 min")

@app.on_event("shutdown")
async def _shutdown():
    global _update_task
    if _update_task:
        _update_task.cancel()
        with suppress(asyncio.CancelledError):
            await _update_task
    print("[shutdown] background task stopped")


# --- Create tables on startup (dev only; use Alembic migrations in prod) ---
@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)

@app.get("/", tags=["meta"])
def health():
    return {"ok": True, "service": "people-in-news", "version": "1.0.0"}

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
        stmt = select(models.Person).where(models.Person.name.ilike(f"%{q}%")).order_by(desc(models.Person.created_at)).limit(limit)
    people = db.execute(stmt).scalars().all()
    return people

# --- Get "cards" view: people with their top-N articles ---
@app.get("/people/cards", response_model=List[schemas.PersonNewsCard], tags=["people"])
def get_people_cards(top: int = Query(3, ge=1, le=10), db: Session = Depends(get_db)):
    p = models.Person
    a = models.Article
    pa = models.PersonArticle

    rn = func.row_number().over(
        partition_by=pa.person_id,
        order_by=(a.published_at.desc().nullslast(), a.created_at.desc())
    )

    subq = (
        select(
            p.id.label("person_id"),
            p.name.label("person_name"),
            p.image_url,
            a.id.label("article_id"),
            a.title,
            a.summary,
            a.link,
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
                "image_url": r.image_url,
                "articles": [],
            }
        cards[pid]["articles"].append({
            "id": r.article_id,
            "title": r.title,
            "summary": r.summary,
            "link": r.link,
            "published_at": r.published_at.isoformat() if r.published_at else None,
        })

    #sort people by their latest article’s published_at desc
    def latest_pub(card):
        first = card["articles"][0]["published_at"] if card["articles"] else None
        return first or ""
    ordered = sorted(cards.values(), key=latest_pub, reverse=True)

    return ordered

# --- Latest articles across everyone ---
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

@app.delete("/debug/people/by-name/{name}")
def delete_person_by_name_sql(name: str, db = Depends(get_db)):
    db.execute(text("""
        DELETE FROM person_articles
        WHERE person_id IN (SELECT id FROM people WHERE lower(name) = lower(:name));
    """), {"name": name})

    # Delete the person
    res = db.execute(text("""
        DELETE FROM people
        WHERE lower(name) = lower(:name)
    """), {"name": name})
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"No person found with name: {name}")

    db.commit()
    return {"deleted": name}