# Copyright 2025 STIRR / Thinking Media
# Licensed under the Apache License, Version 2.0

"""Tools for the STIRR content agent. Uses VODLIX API for real content search."""

import base64
import json
import logging
import os
from typing import Any
from urllib.parse import urljoin

import httpx

try:
    from google.adk.tools.tool_context import ToolContext
except ImportError:
    ToolContext = type("ToolContext", (), {"state": {}})  # minimal mock

logger = logging.getLogger(__name__)

VODLIX_API_BASE = os.getenv("VODLIX_API_BASE", "https://stirr.com/api")
VODLIX_USERNAME = os.getenv("VODLIX_USERNAME", "")
VODLIX_PASSWORD = os.getenv("VODLIX_PASSWORD", "")


def _get_auth_header() -> dict[str, str]:
    """HTTP Basic Auth header for VODLIX."""
    if not VODLIX_USERNAME or not VODLIX_PASSWORD:
        return {}
    credentials = f"{VODLIX_USERNAME}:{VODLIX_PASSWORD}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def _vodlix_video_to_item(video: dict[str, Any], api_base: str) -> dict[str, Any]:
    """Map VODLIX video to ContentShelf item format. Includes play_url for VideoPlayer."""
    video_id = str(video.get("videoid") or video.get("id", ""))
    thumbs = video.get("thumbs", {})
    if isinstance(thumbs, dict):
        image_url = thumbs.get("1920x1080") or thumbs.get("original") or thumbs.get("768x432") or ""
    else:
        image_url = ""

    if image_url and not image_url.startswith("http"):
        image_url = urljoin(api_base.replace("/api", ""), image_url)

    genres = []
    for cat in video.get("categories", []) or []:
        if isinstance(cat, dict) and cat.get("category_name"):
            genres.append(cat["category_name"])
    genre = ", ".join(genres) if genres else video.get("genre", "")

    # play_url: watch page for embed/iframe. VODLIX list API has no hls_url; construct from watch_url or copy_url.
    base_url = api_base.rstrip("/").replace("/api", "") or "https://stirr.com"
    watch_url = video.get("watch_url", "")
    copy_url = video.get("copy_url", "")
    if watch_url:
        play_url = watch_url if watch_url.startswith("http") else urljoin(base_url, watch_url.lstrip("/"))
    elif copy_url and copy_url.startswith("http"):
        play_url = copy_url
    else:
        play_url = f"{base_url}/watch/{video_id}" if video_id else ""

    # Live content may have epg_url or force_hls_http_url for direct HLS (future)
    is_live = video.get("content_type") == 4 or video.get("live") or video.get("live_status")
    hls_url = video.get("epg_url") or video.get("force_hls_http_url") or video.get("hls_url") or ""

    return {
        "id": video_id,
        "title": video.get("title", "Untitled"),
        "genre": genre,
        "image_url": image_url or "https://via.placeholder.com/320x180?text=No+Image",
        "description": (video.get("description") or "")[:200],
        "play_url": play_url,
        "is_live": bool(is_live),
        "hls_url": hls_url or None,  # Direct HLS when available (live epg_url, or DataGraphs streamUrl)
    }


def _search_vodlix(query: str, limit: int) -> list[dict[str, Any]]:
    """Search VODLIX API. Tries v2/search first, falls back to v2/videos/list + filter."""
    headers = _get_auth_header()
    items: list[dict[str, Any]] = []

    # Try v2/search first
    search_url = urljoin(VODLIX_API_BASE.rstrip("/") + "/", "v2/search")
    params = {"q": query, "content_type": 1, "limit": limit}

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(search_url, headers=headers, params=params)
            if response.status_code == 200:
                result = response.json()
                videos = []
                if "data" in result:
                    data = result["data"]
                    if isinstance(data, list):
                        videos = data
                    elif isinstance(data, dict):
                        videos = data.get("videos", data.get("results", []))
                elif "videos" in result:
                    videos = result["videos"]

                for v in videos[:limit]:
                    items.append(_vodlix_video_to_item(v, VODLIX_API_BASE))
    except Exception as e:
        logger.warning(f"VODLIX search failed: {e}")

    # Fallback: fetch from v2/videos/list and filter by query
    if not items:
        list_url = urljoin(VODLIX_API_BASE.rstrip("/") + "/", "v2/videos/list/")
        q_lower = query.lower()
        try:
            with httpx.Client(timeout=30.0) as client:
                for page in range(1, 4):  # Check first 3 pages
                    resp = client.get(
                        list_url,
                        headers=headers,
                        params={"content_type": 1, "limit": 50, "page": page},
                    )
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    results = (data.get("data") or {}).get("results", [])
                    if not results:
                        break
                    for v in results:
                        if len(items) >= limit:
                            break
                        title = (v.get("title") or "").lower()
                        desc = (v.get("description") or "").lower()
                        tags = (v.get("tags") or "").lower()
                        if q_lower in title or q_lower in desc or q_lower in tags:
                            items.append(_vodlix_video_to_item(v, VODLIX_API_BASE))
                    if len(items) >= limit:
                        break
        except Exception as e:
            logger.warning(f"VODLIX list fallback failed: {e}")

    # If still empty, return first page of movies (discovery)
    if not items:
        try:
            list_url = urljoin(VODLIX_API_BASE.rstrip("/") + "/", "v2/videos/list/")
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    list_url,
                    headers=headers,
                    params={"content_type": 1, "limit": limit, "page": 1},
                )
                if resp.status_code == 200:
                    results = (resp.json().get("data") or {}).get("results", [])
                    for v in results[:limit]:
                        items.append(_vodlix_video_to_item(v, VODLIX_API_BASE))
        except Exception as e:
            logger.warning(f"VODLIX discovery fallback failed: {e}")

    return items


def _fetch_live_content(limit: int = 20) -> list[dict[str, Any]]:
    """Fetch live channels from VODLIX (content_type=4, live=true)."""
    headers = _get_auth_header()
    if not headers:
        return []
    list_url = urljoin(VODLIX_API_BASE.rstrip("/") + "/", "v2/videos/list/")
    items: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                list_url,
                headers=headers,
                params={"content_type": 4, "live": "true", "limit": limit, "page": 1},
            )
            if resp.status_code == 200:
                results = (resp.json().get("data") or {}).get("results", [])
                for v in results:
                    items.append(_vodlix_video_to_item(v, VODLIX_API_BASE))
    except Exception as e:
        logger.warning(f"VODLIX live fetch failed: {e}")
    return items


def get_breaking_news(location: str, tool_context: ToolContext, limit: int = 5) -> str:
    """
    Get breaking news / live channels for a location (e.g. Dallas).
    Searches VODLIX live content for location or news keywords.
    """
    logger.info(f"--- TOOL CALLED: get_breaking_news (location={location}) ---")
    if not VODLIX_USERNAME or not VODLIX_PASSWORD:
        return json.dumps({"items": [], "headline": "News", "summary": "VODLIX not configured"})

    live_items = _fetch_live_content(limit=50)
    q = location.lower()
    matches = [
        i for i in live_items
        if q in i["title"].lower() or q in i["genre"].lower() or q in i["description"].lower()
        or "news" in i["title"].lower() or "news" in i["genre"].lower()
    ]
    items = matches[:limit] if matches else live_items[:limit]
    headline = f"Breaking News from {location}" if items else "Breaking News"
    summary = f"{len(items)} live channels" if items else "No live news channels found"
    return json.dumps({"items": items, "headline": headline, "summary": summary})


def get_chapters(video_title: str, tool_context: ToolContext) -> str:
    """
    Get chapters for a documentary or long-form content.
    VODLIX may not have chapter data; returns sample chapters for demo.
    """
    logger.info(f"--- TOOL CALLED: get_chapters (video={video_title}) ---")
    # Sample chapters for demo - real implementation would fetch from VODLIX if available
    chapters = [
        {"id": "ch1", "title": "Introduction", "timestamp": 0},
        {"id": "ch2", "title": "Background & Context", "timestamp": 300},
        {"id": "ch3", "title": "Key Events", "timestamp": 720},
        {"id": "ch4", "title": "Analysis", "timestamp": 1200},
        {"id": "ch5", "title": "Conclusion", "timestamp": 1800},
    ]
    return json.dumps({"chapters": chapters, "videoTitle": video_title or "Documentary"})


def search_content(query: str, tool_context: ToolContext, limit: int = 10) -> str:
    """
    Search STIRR content by query via VODLIX API. Returns JSON list of items for ContentShelf.

    Requires: VODLIX_API_BASE, VODLIX_USERNAME, VODLIX_PASSWORD
    """
    logger.info(f"--- TOOL CALLED: search_content (query={query}, limit={limit}) ---")

    if not VODLIX_USERNAME or not VODLIX_PASSWORD:
        logger.warning("VODLIX credentials not set. Set VODLIX_API_BASE, VODLIX_USERNAME, VODLIX_PASSWORD.")
        return json.dumps({"items": [], "error": "VODLIX credentials not configured"})

    items = _search_vodlix(query, limit)
    logger.info(f" - Found {len(items)} items from VODLIX")
    return json.dumps({"items": items})


def _fetch_video_by_id(video_id: str) -> dict[str, Any] | None:
    """Fetch single video from VODLIX v2/videos/list/{id}."""
    headers = _get_auth_header()
    if not headers:
        return None
    url = urljoin(VODLIX_API_BASE.rstrip("/") + "/", f"v2/videos/list/{video_id}")
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(url, headers=headers)
            if r.status_code == 200:
                data = r.json()
                return data.get("data") if isinstance(data.get("data"), dict) else None
    except Exception as e:
        logger.warning(f"Fetch video {video_id} failed: {e}")
    return None


def ask_about_video(video_id: str, question: str, tool_context: ToolContext) -> str:
    """
    Answer a question about the currently playing video.
    Fetches video metadata from VODLIX, passes to Gemini as context. Phase 2/3.
    """
    logger.info(f"--- TOOL CALLED: ask_about_video (video_id={video_id}, question={question[:50]}...) ---")
    video = _fetch_video_by_id(video_id)
    context_parts = []
    if video:
        context_parts.append(f"Title: {video.get('title', 'Unknown')}")
        if video.get("description"):
            context_parts.append(f"Description: {video['description']}")
        if video.get("tags"):
            context_parts.append(f"Tags: {video['tags']}")
        for cat in video.get("categories", []) or []:
            if isinstance(cat, dict) and cat.get("category_name"):
                context_parts.append(f"Category: {cat['category_name']}")
    context = "\n".join(context_parts) if context_parts else "No metadata available for this video."
    try:
        import litellm
        response = litellm.completion(
            model=os.getenv("LITELLM_MODEL", "gemini/gemini-2.5-flash"),
            messages=[
                {"role": "system", "content": "Answer briefly based only on the video context. If the context doesn't contain the answer, say so."},
                {"role": "user", "content": f"Video context:\n{context}\n\nUser question: {question}"},
            ],
        )
        answer = response.choices[0].message.content or "No answer generated."
    except Exception as e:
        logger.warning(f"Gemini ask_about_video failed: {e}")
        title = video.get("title", "Unknown") if video else "Unknown"
        desc = (video.get("description") or "")[:200] if video else "No metadata."
        answer = f"Based on the video: {title}. {desc} (Full Q&A requires GEMINI_API_KEY.)"
    return json.dumps({"answer": answer})
