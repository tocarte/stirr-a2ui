# Copyright 2025 STIRR / Thinking Media
# Licensed under the Apache License, Version 2.0

"""Tools for the STIRR content agent. Uses VODLIX API for real content search."""

import base64
import json
import logging
import os
import re
from typing import Any, Optional
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


def _search_live_by_query(query: str, limit: int) -> list[dict[str, Any]]:
    """Search live channels by query (station call letters, city, news)."""
    live_items = _fetch_live_content(limit=100)
    if not query or not query.strip():
        return live_items[:limit]
    q = query.lower().strip()
    tokens = [t for t in q.split() if len(t) >= 2]
    matches: list[tuple[int, dict[str, Any]]] = []
    for i in live_items:
        title_l = i["title"].lower()
        genre_l = (i.get("genre") or "").lower()
        desc_l = (i.get("description") or "").lower()
        combined = f"{title_l} {genre_l} {desc_l}"
        if q in combined:
            matches.append((10, i))  # Full query match
        elif tokens:
            n_matched = sum(1 for t in tokens if t in combined)
            if n_matched > 0:
                matches.append((n_matched, i))
    matches.sort(key=lambda x: -x[0])
    return [i for _, i in matches[:limit]] if matches else []


def search_content(query: str, tool_context: ToolContext, limit: int = 10) -> str:
    """
    Search STIRR content by query via VODLIX API. Returns JSON list of items for ContentShelf.
    Searches both VOD (movies) and live channels (news, local stations like WNYC, WLOS, Albany, Asheville).

    Requires: VODLIX_API_BASE, VODLIX_USERNAME, VODLIX_PASSWORD
    """
    logger.info(f"--- TOOL CALLED: search_content (query={query}, limit={limit}) ---")

    if not VODLIX_USERNAME or not VODLIX_PASSWORD:
        logger.warning("VODLIX credentials not set. Set VODLIX_API_BASE, VODLIX_USERNAME, VODLIX_PASSWORD.")
        return json.dumps({"items": [], "error": "VODLIX credentials not configured"})

    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    # 1. Search VOD (movies) first
    vod_items = _search_vodlix(query, limit)
    for i in vod_items:
        vid = i.get("id", "")
        if vid and vid not in seen_ids:
            seen_ids.add(vid)
            items.append(i)

    # 2. Add live channels (news, local stations like WNYC, WLOS, Albany, Asheville)
    live_limit = max(0, limit - len(items))
    if live_limit > 0:
        live_items = _search_live_by_query(query, limit=live_limit)
        for i in live_items:
            vid = i.get("id", "")
            if vid and vid not in seen_ids:
                seen_ids.add(vid)
                items.append(i)

    n_live = sum(1 for i in items if i.get("is_live"))
    logger.info(f" - Found {len(items)} items ({n_live} live, {len(items) - n_live} VOD)")
    return json.dumps({"items": items})


def _fetch_video_by_id(video_id: str) -> Optional[dict[str, Any]]:
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
                inner = data.get("data")
                if isinstance(inner, dict) and "title" in inner:
                    return inner
                if isinstance(inner, dict) and "results" in inner:
                    results = inner.get("results") or []
                    return results[0] if results else None
                if isinstance(inner, list) and inner:
                    return inner[0]
                return inner if isinstance(inner, dict) else None
    except Exception as e:
        logger.warning(f"Fetch video {video_id} failed: {e}")
    return None


def ask_about_video(
    video_id: str,
    question: str,
    tool_context: ToolContext,
    ocr_onscreen_text: Optional[list[str]] = None,
) -> str:
    """
    Answer a question about the currently playing video.
    Phase 3: Intent classifier + context subset + structured output.
    P4-H5: Accepts ocr_onscreen_text from client-side TextDetector (Chrome).
    """
    logger.info(f"--- TOOL CALLED: ask_about_video (video_id={video_id}, question={question[:50]}...) ---")
    video = _fetch_video_by_id(video_id)

    from intent import (
        classify_intent,
        build_context_for_intent,
        build_minimal_context_bundle,
        SYSTEM_PROMPT,
        INTENT_PROMPTS,
    )

    intent = classify_intent(question)
    context_bundle = build_minimal_context_bundle(video)

    # P4-H5: Add client-side OCR when provided
    if ocr_onscreen_text and isinstance(ocr_onscreen_text, list):
        context_bundle.setdefault("ocr", {})["onscreen_text"] = [
            str(t).strip() for t in ocr_onscreen_text if t and str(t).strip()
        ]
        logger.info(f"ocr: added {len(context_bundle['ocr']['onscreen_text'])} on-screen text items")

    # utility_intent: fetch recommendations so the model can suggest "what else to watch"
    if intent == "utility_intent":
        recs: list[dict[str, Any]] = []
        genre = (video or {}).get("genre", "") or ""
        for cat in (video or {}).get("categories") or []:
            if isinstance(cat, dict) and cat.get("category_name"):
                genre = cat.get("category_name", "")
                break
        is_live = (video or {}).get("content_type") == 4 or (video or {}).get("live")
        search_q = (genre or "").strip() or ("news" if is_live else "movies")
        vod_items = _search_vodlix(search_q, limit=6)
        live_items = _search_live_by_query(search_q, limit=6)
        # Fallback: if few results, add discovery (movies, comedy) for variety
        if len(vod_items) + len(live_items) < 4:
            vod_items = vod_items or _search_vodlix("movies", limit=6)
            live_items = live_items or _search_live_by_query("news", limit=4)
        current_title = (video or {}).get("title", "")
        for i in (live_items + vod_items):
            if len(recs) >= 10:
                break
            if i.get("title") == current_title:
                continue
            recs.append({"title": i.get("title", ""), "type": "live" if i.get("is_live") else "vod"})
        if recs:
            context_bundle.setdefault("ui_context", {})["visible_recommendations"] = recs
            logger.info(f"utility_intent: added {len(recs)} recommendations to context")

    context_text = build_context_for_intent(intent, context_bundle)
    intent_instruction = INTENT_PROMPTS.get(intent, INTENT_PROMPTS["general_broadcast_intent"])

    try:
        from pathlib import Path
        from dotenv import load_dotenv
        _env = Path(__file__).parent / ".env"
        if _env.exists():
            load_dotenv(_env)
    except Exception:
        pass

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set")
        title = video.get("title", "Unknown") if video else "Unknown"
        desc = (video.get("description") or "")[:200] if video else "No metadata."
        return json.dumps({
            "answer": f"Based on the video: {title}. {desc} (Set GEMINI_API_KEY in agent/.env for full Q&A.)",
            "answer_type": intent,
            "primary_answer": None,
            "supporting_points": [],
            "confidence": 0.5,
        })

    utility_note = ""
    if intent == "utility_intent":
        utility_note = "\n\nIMPORTANT: The context includes a 'What else to watch' list. You MUST recommend those specific titles. Do NOT say 'the context doesn't contain that' or 'it does not specify what else.' List the titles by name.\n"

    user_prompt = f"""Context for this turn:
{context_text}
{utility_note}
Intent: {intent}
Instruction: {intent_instruction}

User question: {question}

Respond with a JSON object:
{{
  "answer_type": "{intent}",
  "primary_answer": "Your main answer (1-3 sentences, concise, viewer-friendly)",
  "supporting_points": ["Optional bullet 1", "Optional bullet 2"],
  "confidence": 0.0-1.0,
  "suggested_follow_up": "Optional short follow-up suggestion or null"
}}

Return only valid JSON, no markdown or extra text."""

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig

        client = genai.Client(api_key=api_key)
        model = os.getenv("LITELLM_MODEL", "gemini-2.5-flash").replace("gemini/", "")
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        )
        raw = (getattr(response, "text", None) or str(response) or "").strip()
        # Strip markdown code blocks if present
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        answer = data.get("primary_answer") or data.get("answer", raw)
        return json.dumps({
            "answer": answer,
            "answer_type": data.get("answer_type", intent),
            "primary_answer": data.get("primary_answer") or answer,
            "supporting_points": data.get("supporting_points") or [],
            "confidence": float(data.get("confidence", 0.8)),
            "suggested_follow_up": data.get("suggested_follow_up"),
        })
    except json.JSONDecodeError as e:
        logger.warning(f"Gemini returned non-JSON, wrapping: {e}")
        fallback = raw[:2000] if raw else "No answer generated."
        return json.dumps({
            "answer": fallback,
            "answer_type": intent,
            "primary_answer": None,
            "supporting_points": [],
            "confidence": 0.7,
        })
    except Exception as e:
        logger.warning(f"Gemini ask_about_video failed: {e}", exc_info=True)
        title = video.get("title", "Unknown") if video else "Unknown"
        desc = (video.get("description") or "")[:200] if video else "No metadata."
        err_msg = str(e)[:150] if str(e) else "Unknown error"
        return json.dumps({
            "answer": f"Based on the video: {title}. {desc} (Gemini error: {err_msg})",
            "answer_type": intent,
            "primary_answer": None,
            "supporting_points": [],
            "confidence": 0.5,
        })
