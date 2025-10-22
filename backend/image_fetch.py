import os
import time
import asyncio
import httpx
import cv2
import numpy as np
import base64
from io import BytesIO
from typing import Optional, Dict, Tuple
from validators import is_valid_person_name
from sklearn.cluster import KMeans
from dotenv import load_dotenv

load_dotenv()
_IMAGE_CACHE: Dict[str, Tuple[float, str]] = {}  # name_lower -> (expires_at, url)
_IMAGE_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60      # 7 days
_IMAGE_CACHE_LOCK = asyncio.Lock()

# Wikimedia endpoints
WIKI_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")

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

async def upload_to_imgbb(img_base64: str) -> Optional[str]:
    """
    Upload image to ImgBB and return permanent hosted URL.
    
    ImgBB Features:
    - Free unlimited bandwidth
    - No expiration (with expiration=0)
    - 32MB file size limit
    - Direct image URLs
    
    Args:
        img_base64: Base64 encoded image string
    
    Returns:
        Hosted URL (e.g., "https://i.ibb.co/abc123/image.jpg") or None
    """
    if not IMGBB_API_KEY:
        print("⚠️ IMGBB_API_KEY not set!")
        print("   Get your free API key from: https://api.imgbb.com/")
        print("   Then set it: export IMGBB_API_KEY='your_key_here'")
        return None
    
    try:
        print("☁️ Uploading to ImgBB...")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.imgbb.com/1/upload",
                data={
                    "key": IMGBB_API_KEY,
                    "image": img_base64,
                    "expiration": 0  # 0 = never expires (permanent)
                },
                timeout=60
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("success"):
                url = data["data"]["url"]
                display_url = data["data"]["display_url"]
                delete_url = data["data"]["delete_url"]
                
                print(f"✅ Uploaded successfully!")
                print(f"   URL: {url}")
                print(f"   Size: {data['data']['size']} bytes")
                
                # Return the direct image URL (best for database)
                return url
            else:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                print(f"❌ ImgBB upload failed: {error_msg}")
                return None
            
    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP error: {e.response.status_code}")
        print(f"   Response: {e.response.text}")
        return None
    except Exception as e:
        print(f"❌ Upload error: {e}")
        return None


async def _anime_filter(image_url: str) -> Optional[str]:
    try:
        print(f"📥 Downloading image from: {image_url}")
        
        # Step 1: Download image from URL
        async with httpx.AsyncClient() as client:
            response = await client.get(image_url, timeout=30)
            response.raise_for_status()
            image_data = response.content
        
        # Convert bytes to OpenCV image (equivalent to cv2.imread)
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            print("❌ Could not decode image")
            return None
        
        # Convert BGR to RGB (same as your notebook)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        print(f"✅ Image loaded: {img.shape[1]}x{img.shape[0]} pixels")
        print(f"🎨 Applying anime cartoon filter...")
        
        # ========== YOUR EXACT NOTEBOOK CODE STARTS HERE ==========
        
        # Edge mask generation
        line_size = 7
        blur_value = 7
        
        gray_img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        gray_blur = cv2.medianBlur(gray_img, blur_value)
        edges = cv2.adaptiveThreshold(
            gray_blur, 
            255, 
            cv2.ADAPTIVE_THRESH_MEAN_C, 
            cv2.THRESH_BINARY, 
            line_size, 
            blur_value
        )
        
        # Color quantization with KMeans clustering
        k = 7
        data = img.reshape(-1, 3)
        
        kmeans = KMeans(n_clusters=k, random_state=42).fit(data)
        img_reduced = kmeans.cluster_centers_[kmeans.labels_]
        img_reduced = img_reduced.reshape(img.shape)
        img_reduced = img_reduced.astype(np.uint8)
        
        # Bilateral Filter
        blurred = cv2.bilateralFilter(img_reduced, d=7, sigmaColor=200, sigmaSpace=200)
        cartoon = cv2.bitwise_and(blurred, blurred, mask=edges)
        
        print(f"✅ Anime filter applied!")
        
        # Step 4: Convert to base64
        cartoon_bgr = cv2.cvtColor(cartoon, cv2.COLOR_RGB2BGR)
        _, buffer = cv2.imencode('.jpg', cartoon_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        img_bytes = buffer.tobytes()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
        
        print(f"📦 Image size: {len(img_bytes) / 1024:.1f} KB")
        
        # Step 5: Upload to ImgBB
        hosted_url = await upload_to_imgbb(img_base64)
        
        if hosted_url:
            return hosted_url
        else:
            # Fallback: return data URL if upload fails
            print("⚠️ Upload failed, returning data URL")
            return f"data:image/jpeg;base64,{img_base64}"
        
    except Exception as e:
        print(f"❌ [Anime Filter] Error: {e}")
        import traceback
        traceback.print_exc()
        return None

async def _fetch_wikipedia_primary_image(client: httpx.AsyncClient, person_name: str) -> Optional[str]:
   
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
                # Apply anime filter
                anime_url = await _anime_filter(url)
                final_url = anime_url if anime_url else url
                print(f"🎯 Final image URL for '{person_name}': {final_url}")
                await _set_cached(person_name, final_url)
                return final_url
    except Exception as e:
        print("[Wikimedia] image fetch error:", e)

    
    fallback = _avatar(person_name)
    await _set_cached(person_name, fallback)  # cache the fallback too
    return fallback