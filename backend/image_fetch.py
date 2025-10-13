import os
import time
import asyncio
import httpx
from typing import Optional, Dict, Tuple
from validators import is_valid_person_name


_IMAGE_CACHE: Dict[str, Tuple[float, str]] = {}  # name_lower -> (expires_at, url)
_IMAGE_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60      # 7 days
_IMAGE_CACHE_LOCK = asyncio.Lock()

# Wikimedia endpoints
WIKI_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# Identify your app per Wikimedia's requirements:
USER_AGENT = os.getenv(
    "WIKIMEDIA_USER_AGENT",
    "PeopleNewsBot/1.0 (contact: meenabanavatu44@gmail.com)"
)

def _avatar(person_name: str) -> str:
    return f"https://ui-avatars.com/api/?name={person_name.replace(' ', '+')}&size=400&background=random"

async def _get_cached(person_name: str) -> Optional[str]:
    name_key = person_name.strip().lower()
    async with _IMAGE_CACHE_LOCK:
        hit = _IMAGE_CACHE.get(name_key)
        if not hit:
            return None
        expires_at, url = hit
        if time.time() > expires_at:
            # expired
            _IMAGE_CACHE.pop(name_key, None)
            return None
        return url

async def _set_cached(person_name: str, url: str) -> None:
    name_key = person_name.strip().lower()
    async with _IMAGE_CACHE_LOCK:
        _IMAGE_CACHE[name_key] = (time.time() + _IMAGE_CACHE_TTL_SECONDS, url)

async def _fetch_wikipedia_primary_image(client: httpx.AsyncClient, person_name: str) -> Optional[str]:
    """
    Try to get a primary image from Wikipedia using 'generator=search' + 'pageimages'.
    Returns a reasonably sized thumbnail/original URL if found.
    """
    params = {
        "action": "query",
        "format": "json",
        "prop": "pageimages",
        "piprop": "original|thumbnail",
        "pithumbsize": 600,
        "generator": "search",
        "gsrsearch": person_name,
        "gsrlimit": 1,
        "origin": "*",
    }
    r = await client.get(WIKI_API, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
    r.raise_for_status()
    data = r.json()
    pages = (data.get("query") or {}).get("pages") or {}
    if not pages:
        return None
    
    for _, page in pages.items():
        # Prefer original if available, otherwise thumbnail
        original = (page.get("original") or {}).get("source")
        if isinstance(original, str) and original.startswith("http"):
            return original
        thumb = (page.get("thumbnail") or {}).get("source")
        if isinstance(thumb, str) and thumb.startswith("http"):
            return thumb
    return None

async def _fetch_commons_image_search(client: httpx.AsyncClient, person_name: str) -> Optional[str]:
    """
    Fallback: search Wikimedia Commons for a file (namespace=6).
    Then resolve it via imageinfo -> best available URL (width ~600px if possible).
    """
    # 1) Find a File:... title that matches the person
    search_params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": person_name,
        "srnamespace": 6,    # File namespace
        "srlimit": 1,
        "origin": "*",
    }
    rs = await client.get(COMMONS_API, params=search_params, headers={"User-Agent": USER_AGENT}, timeout=20)
    rs.raise_for_status()
    sdata = rs.json()
    results = (sdata.get("query") or {}).get("search") or []
    if not results:
        return None

    file_title = results[0].get("title")  # e.g., "File:Some_Person_2024.jpg"
    if not file_title:
        return None

    # 2) Resolve that file to a usable URL via imageinfo (prefer ~600px width)
    info_params = {
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "titles": file_title,
        "iiprop": "url",
        "iiurlwidth": 600,
        "origin": "*",
    }
    ri = await client.get(COMMONS_API, params=info_params, headers={"User-Agent": USER_AGENT}, timeout=20)
    ri.raise_for_status()
    idata = ri.json()
    pages = (idata.get("query") or {}).get("pages") or {}
    for _, page in pages.items():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        # Prefer the sized URL if present; otherwise the original url
        sized = infos[0].get("thumburl")
        if isinstance(sized, str) and sized.startswith("http"):
            return sized
        original = infos[0].get("url")
        if isinstance(original, str) and original.startswith("http"):
            return original
    return None

async def generate_person_image(person_name: str) -> str:
    if not is_valid_person_name(person_name):
        raise ValueError(f"🚫 Invalid person name: {person_name}")
    
    # Cache check
    cached = await _get_cached(person_name)
    if cached:
        return cached
    
    try:
        async with httpx.AsyncClient() as client:
            # 1) Wikipedia page primary image
            url = await _fetch_wikipedia_primary_image(client, person_name)
            if not url:
                # 2) Wikimedia Commons direct file search
                url = await _fetch_commons_image_search(client, person_name)

            if url and url.startswith("http"):
                await _set_cached(person_name, url)
                return url
    except Exception as e:
        print("[Wikimedia] image fetch error:", e)

    
    fallback = _avatar(person_name)
    await _set_cached(person_name, fallback)  # cache the fallback too
    return fallback
