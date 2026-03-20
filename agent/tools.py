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


def _epg_channel_id_to_hls_url(epg_channel_id: str) -> str:
    """
    Construct Amagi HLS URL from VODLIX epg_channel_id.
    Pattern from STIRR watch page inspection (WNYT Albany): amg01942-amg01942c5-stirr-us-10184.
    See stirr-control/docs/VODLIX_NATIVE_HLS_FINDINGS.md
    Only applies to Amagi channels (epg_channel_id starts with amg); others (FTFLive.com, 1312, LSN) use different CDNs.
    """
    if not epg_channel_id or not isinstance(epg_channel_id, str):
        return ""
    epg = epg_channel_id.strip()
    epg_lo = epg.lower()
    if len(epg) < 8 or not epg_lo.startswith("amg"):
        return ""
    prefix = epg_lo[:8]
    return f"https://{prefix}-{epg_lo}-stirr-us-10184.playouts.now.amagi.tv/playlistR720p.m3u8"


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

    # Live content: prefer epg_channel_id → Amagi HLS (from watch page inspection), else API fields
    is_live = video.get("content_type") == 4 or video.get("live") or video.get("live_status")
    hls_url = (
        video.get("force_hls_http_url")
        or video.get("hls_url")
        or (_epg_channel_id_to_hls_url(video.get("epg_channel_id", "")) if is_live else "")
        or ""
    )

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


def fetch_breaking_news_headlines(market: str, limit: int = 5) -> dict[str, Any]:
    """
    Fetch breaking news headlines for a market using Gemini with Google Search grounding.
    P4-H12e: Preload chat when user selects local station.
    Returns: {"headlines": ["...", ...], "summary": "..."} or {"headlines": [], "summary": "..."} on error.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set")
        return {"headlines": [], "summary": "Set GEMINI_API_KEY for breaking news."}

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig, Tool, GoogleSearch

        client = genai.Client(api_key=api_key)
        model = os.getenv("LITELLM_MODEL", "gemini-2.5-flash").replace("gemini/", "")

        prompt = f"""What are the top {limit} breaking news stories in {market} right now?
Return ONLY a bullet list. No intro sentence. One line per story. Be concise.
Format exactly:
- Headline 1
- Headline 2
- Headline 3"""

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(tools=[Tool(google_search=GoogleSearch())]),
        )
        text = (getattr(response, "text", None) or str(response) or "").strip()
        if not text:
            return {"headlines": [], "summary": f"No headlines for {market}."}

        # Parse bullets: lines starting with - • * or split by " * " when Gemini returns inline
        raw_lines = [l.strip() for l in text.split("\n") if l.strip()]
        bullets = []
        for line in raw_lines:
            if line.startswith("-") or line.startswith("•") or line.startswith("*"):
                bullets.append(re.sub(r"^[-•*]\s*", "", line).strip())
            elif " * " in line:
                for part in line.split(" * "):
                    p = part.strip()
                    if p and len(p) > 10 and "here are the top" not in p.lower():
                        bullets.append(p[:120])
        headlines = [h for h in bullets[:limit] if h and len(h) > 5]
        if not headlines and text:
            headlines = [text[:150]]

        return {"headlines": headlines, "summary": f"Top stories in {market}"}
    except Exception as e:
        logger.warning(f"fetch_breaking_news_headlines failed: {e}")
        return {"headlines": [], "summary": str(e)}


def fetch_news_search(query: str, market: str, limit: int = 3) -> dict[str, Any]:
    """
    Search for news about a specific topic in a market. Used when user clicks a headline.
    Returns: {"headlines": ["...", ...], "summary": "..."}
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return {"headlines": [], "summary": "Set GEMINI_API_KEY."}

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig, Tool, GoogleSearch

        client = genai.Client(api_key=api_key)
        model = os.getenv("LITELLM_MODEL", "gemini-2.5-flash").replace("gemini/", "")

        prompt = f"""Find {limit} recent news articles about this topic in {market}: "{query[:100]}"
Return ONLY a bullet list. No intro. One line per story.
- Story 1
- Story 2"""

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(tools=[Tool(google_search=GoogleSearch())]),
        )
        text = (getattr(response, "text", None) or str(response) or "").strip()
        if not text:
            return {"headlines": [], "summary": f"No additional stories for: {query[:50]}..."}

        bullets = []
        for line in text.split("\n"):
            line = line.strip()
            if line and (line.startswith("-") or line.startswith("•") or line.startswith("*")):
                h = re.sub(r"^[-•*]\s*", "", line).strip()[:120]
                if h and len(h) > 5:
                    bullets.append(h)
        headlines = bullets[:limit] if bullets else [text[:150]]

        return {"headlines": headlines, "summary": f"More on: {query[:40]}..."}
    except Exception as e:
        logger.warning(f"fetch_news_search failed: {e}")
        return {"headlines": [], "summary": str(e)}


def fetch_weather_widget(location: str) -> dict[str, Any]:
    """
    P4-H12b: Fetch structured weather data for a location using Gemini + Google Search grounding.
    Returns: { location, temp_f, condition, forecast, humidity, alerts, summary }
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return {"error": "GEMINI_API_KEY not set", "location": location, "summary": "Set GEMINI_API_KEY for weather."}

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig, Tool, GoogleSearch

        client = genai.Client(api_key=api_key)
        model = os.getenv("LITELLM_MODEL", "gemini-2.5-flash").replace("gemini/", "")

        prompt = f"""What is the current weather in {location} right now? Use web search.
For coastal/beach locations, also include tide times (high and low) for today.
Return ONLY valid JSON, no markdown. Include all fields you can find:
{{
  "location": "{location}",
  "temp_f": number (current temp in Fahrenheit),
  "high_f": number (today high) or null,
  "low_f": number (today low) or null,
  "feels_like_f": number (feels like temp) or null,
  "condition": "string (e.g. Partly Cloudy, Rain)",
  "forecast": "string (1-2 sentence outlook for today/tomorrow)",
  "humidity": "string (e.g. 65%) or null",
  "wind_speed": "string (e.g. 9 mph) or null",
  "wind_gust": "string (e.g. 25 mph) or null",
  "wind_direction": "string (e.g. W, from the west) or null",
  "wind_degrees": number (0-360, direction wind is FROM, e.g. 270 for west) or null,
  "precipitation_today": "string (e.g. 0 in) or null",
  "precipitation_tomorrow": "string (e.g. 0.55 in) or null",
  "uv_index": number (0-11) or null,
  "visibility": "string (e.g. 11 miles) or null",
  "air_quality": number (AQI 0-500) or null,
  "sunrise": "string (e.g. 6:59 AM) or null",
  "sunset": "string (e.g. 7:08 PM) or null",
  "alerts": ["alert text with time and source (e.g. Winter Weather Advisory until 8 AM EDT Fri)"] or [],
  "summary": "string (1 sentence viewer-friendly summary)",
  "feels_like_note": "string (e.g. Wind is making it feel colder) or null",
  "dew_point": "string (e.g. 25°F) or null",
  "pressure": "string (e.g. 30.09 inHg) or null",
  "pressure_trend": "string (Low, Normal, High) or null",
  "moon_phase": "string (e.g. Waxing Crescent) or null",
  "moon_illumination": number (0-100) or null,
  "moon_next_full": "string (e.g. 5 days until full moon) or null",
  "high_avg_f": number (average high for date) or null,
  "low_avg_f": number (average low for date) or null,
  "visibility_note": "string (e.g. Perfectly clear view) or null",
  "hourly": [{{"hour": "e.g. 2 PM", "temp_f": number, "condition": "string", "icon": "emoji e.g. ☀️"}}] or [],
  "daily": [{{"day": "e.g. Fri", "low_f": number, "high_f": number, "condition": "string", "icon": "emoji"}}] or [],
  "tides": [{{"time": "e.g. 6:24 AM", "type": "high" or "low", "height_ft": "e.g. 5.2 ft"}}] or []
}}"""

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(tools=[Tool(google_search=GoogleSearch())]),
        )
        raw = (getattr(response, "text", None) or str(response) or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
            data.setdefault("location", location)
            data.setdefault("summary", f"Weather in {location}")
            return data
        except json.JSONDecodeError:
            return {"location": location, "summary": raw[:200] or f"Weather in {location}", "error": "Parse failed"}
    except Exception as e:
        logger.warning(f"fetch_weather_widget failed: {e}")
        return {"error": str(e), "location": location, "summary": f"Weather unavailable for {location}"}


def fetch_traffic_widget(location: str) -> dict[str, Any]:
    """
    P4-H12b: Fetch structured traffic data for a location using Gemini + Google Search grounding.
    Returns: { location, conditions, delays, accidents, summary }
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return {"error": "GEMINI_API_KEY not set", "location": location, "summary": "Set GEMINI_API_KEY for traffic."}

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig, Tool, GoogleSearch

        client = genai.Client(api_key=api_key)
        model = os.getenv("LITELLM_MODEL", "gemini-2.5-flash").replace("gemini/", "")

        prompt = f"""What are the current traffic and road conditions in {location} right now? Use web search.
Return ONLY valid JSON, no markdown:
{{
  "location": "{location}",
  "conditions": "string (overall traffic/road conditions)",
  "delays": ["list of delays or construction"] or [],
  "accidents": ["any reported accidents"] or [],
  "summary": "string (1-2 sentence viewer-friendly summary)"
}}"""

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(tools=[Tool(google_search=GoogleSearch())]),
        )
        raw = (getattr(response, "text", None) or str(response) or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
            data.setdefault("location", location)
            data.setdefault("summary", f"Traffic in {location}")
            return data
        except json.JSONDecodeError:
            return {"location": location, "summary": raw[:200] or f"Traffic in {location}", "error": "Parse failed"}
    except Exception as e:
        logger.warning(f"fetch_traffic_widget failed: {e}")
        return {"error": str(e), "location": location, "summary": f"Traffic unavailable for {location}"}


def fetch_finance_widget(query: str) -> dict[str, Any]:
    """
    P4-H12b: Fetch structured finance/stock data using Gemini + Google Search grounding.
    Query can be ticker (AAPL) or company name (Tesla).
    Returns: { symbol, name, price, change, change_pct, summary }
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return {"error": "GEMINI_API_KEY not set", "summary": "Set GEMINI_API_KEY for finance."}

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig, Tool, GoogleSearch

        client = genai.Client(api_key=api_key)
        model = os.getenv("LITELLM_MODEL", "gemini-2.5-flash").replace("gemini/", "")

        prompt = f"""What is the current stock price for "{query}"? Use web search for real-time data.
Return ONLY valid JSON, no markdown:
{{
  "symbol": "string (e.g. AAPL)",
  "name": "string (company name)",
  "price": number (current price),
  "change": number (dollar change, can be negative),
  "change_pct": "string (e.g. +1.2%)",
  "summary": "string (1 sentence viewer-friendly summary)"
}}"""

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(tools=[Tool(google_search=GoogleSearch())]),
        )
        raw = (getattr(response, "text", None) or str(response) or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
            data.setdefault("summary", f"Stock info for {query}")
            return data
        except json.JSONDecodeError:
            return {"summary": raw[:200] or f"Finance info for {query}", "error": "Parse failed"}
    except Exception as e:
        logger.warning(f"fetch_finance_widget failed: {e}")
        return {"error": str(e), "summary": f"Finance unavailable for {query}"}


def match_headline_to_segment(headline: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """
    P4-H12d: Match a news headline to a transcript chunk; return start_ms for seek-to-moment.
    Uses Gemini to find the best matching chunk by semantic similarity.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return {"start_ms": None, "error": "GEMINI_API_KEY not set"}

    if not headline or not chunks:
        return {"start_ms": None}

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig

        client = genai.Client(api_key=api_key)
        model = os.getenv("LITELLM_MODEL", "gemini-2.5-flash").replace("gemini/", "")

        chunks_str = "\n".join(
            f"- [{c.get('start_ms', 0)}ms] {c.get('text', '')[:150]}"
            for c in chunks[:30]
        )
        prompt = f"""Given this news headline and these video transcript chunks (with start_ms), which chunk best discusses or relates to the headline?
Return ONLY valid JSON: {{ "start_ms": number or null, "reason": "brief reason" }}
If no good match, use "start_ms": null.

Headline: {headline[:200]}

Chunks:
{chunks_str}"""

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(),
        )
        raw = (getattr(response, "text", None) or str(response) or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
            start_ms = data.get("start_ms")
            if start_ms is not None and isinstance(start_ms, (int, float)):
                return {"start_ms": int(start_ms), "reason": data.get("reason", "")}
            return {"start_ms": None, "reason": data.get("reason", "")}
        except json.JSONDecodeError:
            return {"start_ms": None}
    except Exception as e:
        logger.warning(f"match_headline_to_segment failed: {e}")
        return {"start_ms": None, "error": str(e)}


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


def fetch_video_by_id(video_id: str) -> dict[str, Any]:
    """
    P4-F2: Fetch VODLIX video by ID; return ContentShelf item format with play_url (copy_url/watch page).
    Used when loading video from URL param or when only ID is available.
    """
    if not video_id or not str(video_id).strip():
        return {"error": "video_id required", "id": ""}
    vid = str(video_id).strip()
    video = _fetch_video_by_id(vid)
    if not video:
        return {"error": f"Video {vid} not found", "id": vid}
    item = _vodlix_video_to_item(video, VODLIX_API_BASE)
    return item


def ask_about_video(
    video_id: str,
    question: str,
    tool_context: ToolContext,
    ocr_onscreen_text: Optional[list[str]] = None,
    vision_local: Optional[dict[str, Any]] = None,
    frame_image_base64: Optional[str] = None,
    transcript_local: Optional[dict[str, Any]] = None,
    last_assistant_message: Optional[str] = None,
    ad_break_state: Optional[str] = None,
) -> str:
    """
    Answer a question about the currently playing video.
    Phase 3: Intent classifier + context subset + structured output.
    P4-H5: Accepts ocr_onscreen_text from client-side TextDetector (Chrome).
    P4-H5b: Accepts vision_local { scene, ocr } from Gemini Nano (Chrome Prompt API).
    P4-H6: Accepts frame_image_base64 for server-side Gemini Vision (when client can capture).
    Prefers vision_local when present; else frame_image_base64 for Gemini Vision; else ocr_onscreen_text.
    """
    logger.info(f"--- TOOL CALLED: ask_about_video (video_id={video_id}, question={question[:50]}...) ---")
    video = _fetch_video_by_id(video_id)

    from intent import (
        classify_intent,
        needs_web_retrieval,
        build_context_for_intent,
        build_minimal_context_bundle,
        SYSTEM_PROMPT,
        INTENT_PROMPTS,
    )
    from moment import (
        detect_moment,
        get_moment_prompt_addition,
        MOMENT_GO,
        MOMENT_DO,
        MOMENT_BUY,
    )

    intent = classify_intent(question)
    # P4-H10: Moment detection before LLM
    is_live = bool(video and (video.get("content_type") == 4 or video.get("live")))
    player_state = {"video_id": video_id, "is_live": is_live}
    moment = detect_moment(question, session={}, player_state=player_state)
    moment_prompt = get_moment_prompt_addition(moment)
    logger.info(f"ask_about_video: moment={moment} intent={intent} ad_break_state={ad_break_state}")

    # P4-H13: Ad break gate per spec §5.3 (when ad_break_state provided and live)
    if is_live and ad_break_state:
        if ad_break_state in ("pre", "mid"):
            logger.info("ask_about_video: P4-H13 ad_suppression | ad_break_state=%s", ad_break_state)
            return json.dumps({
                "answer": "An ad break is in progress. Ask again when the program returns.",
                "answer_type": intent,
                "primary_answer": "An ad break is in progress. Ask again when the program returns.",
                "supporting_points": [],
                "confidence": 1.0,
                "suggested_follow_up": None,
                "location_entities": [],
                "moment": moment,
                "ad_break_suppressed": True,
            })
        if ad_break_state == "post" and moment == MOMENT_BUY:
            logger.info("ask_about_video: P4-H13 BUY suppressed post-ad")
            return json.dumps({
                "answer": "Let me find that for you — one moment.",
                "answer_type": intent,
                "primary_answer": "Let me find that for you — one moment.",
                "supporting_points": [],
                "confidence": 1.0,
                "suggested_follow_up": "Ask again in a few seconds when we're back.",
                "location_entities": [],
                "moment": moment,
                "ad_break_suppressed": True,
            })
    context_bundle = build_minimal_context_bundle(video)

    # P4-H5b: Prefer vision_local (Gemini Nano) when provided
    if vision_local and isinstance(vision_local, dict):
        scene = vision_local.get("scene")
        ocr_list = vision_local.get("ocr")
        if isinstance(scene, str) and scene.strip():
            context_bundle.setdefault("vision", {})["scene_summary"] = scene.strip()
            logger.info("vision: added scene_summary from vision_local")
        if isinstance(ocr_list, list) and ocr_list:
            context_bundle.setdefault("ocr", {})["onscreen_text"] = [
                str(t).strip() for t in ocr_list if t and str(t).strip()
            ]
            logger.info(f"ocr: added {len(context_bundle['ocr']['onscreen_text'])} on-screen text from vision_local")
    # P4-H5: Fallback to TextDetector OCR when vision_local not provided
    elif ocr_onscreen_text and isinstance(ocr_onscreen_text, list):
        context_bundle.setdefault("ocr", {})["onscreen_text"] = [
            str(t).strip() for t in ocr_onscreen_text if t and str(t).strip()
        ]
        logger.info(f"ocr: added {len(context_bundle['ocr']['onscreen_text'])} on-screen text items (TextDetector)")

    # Transcript from textTracks (WebVTT/captions)
    if transcript_local and isinstance(transcript_local, dict):
        trans_text = transcript_local.get("text") or transcript_local.get("current_text", "")
        if isinstance(trans_text, str) and trans_text.strip():
            context_bundle.setdefault("transcript", {})["current_text"] = trans_text.strip()
            logger.info(f"transcript: added {len(trans_text)} chars from textTracks")

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
    intent_instruction = INTENT_PROMPTS.get(intent, INTENT_PROMPTS["general_broadcast_intent"]) + moment_prompt

    recent_block = ""
    if last_assistant_message and isinstance(last_assistant_message, str) and last_assistant_message.strip():
        recent_block = (
            f"\nPrevious assistant answer (user may be asking a follow-up about something we just mentioned):\n"
            f"{last_assistant_message.strip()[:2000]}\n\n"
        )

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
            "moment": moment,
        })

    utility_note = ""
    if intent == "utility_intent":
        utility_note = "\n\nIMPORTANT: The context includes a 'What else to watch' list. You MUST recommend those specific titles. Do NOT say 'the context doesn't contain that' or 'it does not specify what else.' List the titles by name.\n"

    # P4-H9 + P4-H10: Web retrieval when needed or moment is GO/DO/BUY
    use_web = needs_web_retrieval(question) or moment in (MOMENT_GO, MOMENT_DO, MOMENT_BUY)
    web_note = ""
    if use_web:
        web_note = "\n\nWeb search is enabled. Use real-time web results to enrich your answer (e.g. for people, places, weather, traffic, how-to). Combine on-screen context with web data when both are relevant.\n"

    # P4-H7: When user asks "what's on screen" but no frame/OCR was captured, use best-effort inference
    has_vision = bool(
        (vision_local and (vision_local.get("scene") or vision_local.get("ocr")))
        or (frame_image_base64 and len(frame_image_base64) > 100)
        or (ocr_onscreen_text and len(ocr_onscreen_text) > 0)
    )
    onscreen_no_vision_note = ""
    if intent == "onscreen_intent" and not has_vision:
        onscreen_no_vision_note = (
            "\n\nNo video frame or on-screen text was captured. Infer from program metadata (title, "
            "description, genre) using 'looks like' or 'appears to be.' Give a helpful viewer-facing answer. "
            "If you can infer the program type (e.g. local news, sports), describe what you'd expect to see. "
            "Do NOT refuse or say 'I couldn't see the screen.' Optionally suggest the Capture button for "
            "more accurate visuals.\n"
        )

    user_prompt = f"""Context for this turn:
{recent_block}{context_text}
{utility_note}{web_note}{onscreen_no_vision_note}
Intent: {intent}
Instruction: {intent_instruction}

User question: {question}

Respond with a JSON object:
{{
  "answer_type": "{intent}",
  "primary_answer": "Your main answer (1-3 sentences, concise, viewer-friendly)",
  "supporting_points": ["Optional bullet 1", "Optional bullet 2"],
  "confidence": 0.0-1.0,
  "suggested_follow_up": "Context-aware follow-up derived from on-screen content (people, topics, entities). E.g. 'What did Powell say about interest rates?' or 'More on the Fed' — NOT generic like 'What's coming up next?'",
  "location_entities": []
}}
Extract location_entities: cities/towns/regions from context (OCR, transcript, channel) for weather links. Examples: Albany, Saratoga, Glens Falls. Use [] if none.

Return only valid JSON, no markdown or extra text."""

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig, Part, Blob, Tool, GoogleSearch

        client = genai.Client(api_key=api_key)
        model = os.getenv("LITELLM_MODEL", "gemini-2.5-flash").replace("gemini/", "")

        gen_config = (
            GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[Tool(google_search=GoogleSearch())],
            )
            if use_web
            else GenerateContentConfig(system_instruction=SYSTEM_PROMPT)
        )
        if use_web:
            logger.info("P4-H9: Using Google Search grounding for web retrieval")

        # P4-H6: When frame_image_base64 present, use Gemini Vision (multimodal)
        if frame_image_base64 and isinstance(frame_image_base64, str) and len(frame_image_base64) > 100:
            try:
                img_bytes = base64.b64decode(frame_image_base64)
                image_part = Part(inline_data=Blob(mime_type="image/jpeg", data=img_bytes))
                text_part = Part.from_text(text=user_prompt)
                contents = [image_part, text_part]
                logger.info("Using Gemini Vision with frame image")
            except Exception as e:
                logger.warning(f"Failed to decode frame_image_base64, using text-only: {e}")
                contents = user_prompt
        else:
            contents = user_prompt

        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=gen_config,
        )
        raw = (getattr(response, "text", None) or str(response) or "").strip()
        # Strip markdown code blocks if present
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        # Extract JSON object if wrapped in extra text (e.g. "Here is the response:\n{...}")
        data = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            if start >= 0:
                depth, end = 0, start
                for i, c in enumerate(raw[start:], start):
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
                if depth == 0:
                    try:
                        data = json.loads(raw[start : end + 1])
                    except json.JSONDecodeError:
                        pass
        if not data:
            raise json.JSONDecodeError("No valid JSON", raw, 0)
        answer = data.get("primary_answer") or data.get("answer", raw)
        locs = data.get("location_entities")
        if not isinstance(locs, list):
            locs = []
        locs = [str(x).strip() for x in locs if x and str(x).strip() and len(str(x)) < 50]
        return json.dumps({
            "answer": answer,
            "answer_type": data.get("answer_type", intent),
            "primary_answer": data.get("primary_answer") or answer,
            "supporting_points": data.get("supporting_points") or [],
            "confidence": float(data.get("confidence", 0.8)),
            "suggested_follow_up": data.get("suggested_follow_up"),
            "location_entities": locs,
            "moment": moment,
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
            "moment": moment,
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
            "moment": moment,
        })


# --- STIRR Moments Engine MVP ---
# See stirr-platform-nextgen/frontend/lib/moments/

MOMENTS_SYSTEM_PROMPT = """You are STIRR's live TV companion.

Your job is to help viewers understand what they are watching right now.
Use the supplied evidence to answer clearly and concisely.

Rules:
- Prioritize the most relevant evidence for the question.
- Do NOT repeat the channel/station name (e.g. "NewsChannel 13 - WNYT") in primary_answer — it is already visible in the UI. Describe the program or content instead.
- If evidence is partial, make a careful best-effort inference.
- Never say the context is missing if useful evidence exists.
- If uncertain, use phrases like "it looks like" or "this appears to be".
- Keep answers concise and grounded.
- suggested_follow_up: MUST be context-aware (People also ask style). Derive from what's on screen: segment topic, people/entities (e.g. Powell, Fed), program name. Examples: "What did Powell say about interest rates?", "More on the Fed", "What's the latest on [topic]?". NEVER use generic prompts like "What's coming up next?" or "Would you like to know what's next?"
- When "Previous assistant answer" is provided: the user may be asking a follow-up (e.g. "What is SkillsUSA?" after we mentioned SkillsUSA). Use that context. Infer from what we just described (e.g. "Based on the scene we discussed, SkillsUSA appears to be an organization that runs competitions..."). Do NOT say "I don't see any information" if we just mentioned it.
- location_entities: Extract cities, towns, regions from OCR, transcript, channel name (e.g. Albany, Saratoga, Glens Falls). Used for weather links. Return [] if none.
- Return valid JSON only."""


def _moments_join_list(values: Optional[list[str]]) -> str:
    return " | ".join(v for v in (values or []) if v) if values else "none"


def _moments_segment_block(req: dict[str, Any]) -> str:
    """Segment summary block when available. Spec 24.13."""
    seg = req.get("segment_summary") or {}
    active = req.get("active_segment") or {}
    if not seg and not active:
        return ""
    seg_type = seg.get("segment_type") or active.get("segment_type") or "unknown"
    summary = seg.get("summary") or active.get("summary") or "none"
    return f"Segment type: {seg_type}\nSegment summary: {summary}\n\n"


def _moments_recent_context_block(req: dict[str, Any]) -> str:
    """Previous assistant message for follow-up context (e.g. 'What is SkillsUSA?' after discussing SkillsUSA)."""
    last = req.get("last_assistant_message") or ""
    if not last or not isinstance(last, str) or not last.strip():
        return ""
    return f"Previous assistant answer (user may be asking a follow-up about something we just mentioned):\n{last.strip()}\n\n"


def _moments_select_prompt(req: dict[str, Any]) -> str:
    """Build prompt for Moments API based on user_message intent. Spec 24.13."""
    q = (req.get("user_message") or "").lower()
    player = req.get("player") or {}
    perception = req.get("perception") or {}

    channel = player.get("channel_name") or player.get("channel_id", "")
    is_live = player.get("is_live", True)
    current_scene = perception.get("current_scene") or "none"
    persistent_ocr = _moments_join_list(perception.get("persistent_ocr"))
    current_ocr = _moments_join_list(perception.get("current_ocr"))
    recent_scenes = _moments_join_list(perception.get("recent_scenes"))
    seg_block = _moments_segment_block(req)
    recent_block = _moments_recent_context_block(req)

    transcript = (
        (req.get("transcript_local") or {}).get("text")
        or (req.get("transcript_server") or {}).get("text")
        or "none"
    )

    if re.search(r"what am i watching|what channel|is this live", q):
        return f"""Question: {req['user_message']}
{recent_block}Channel: {channel}
Is live: {is_live}
{seg_block}Current scene: {current_scene}
Persistent on-screen text: {persistent_ocr}
Current on-screen text: {current_ocr}
Transcript: {transcript}

Prioritize:
1. channel metadata
2. segment type and summary (when present)
3. persistent on-screen text
4. transcript
5. current scene

Return JSON:
{{
  "primary_answer": string,
  "supporting_points": string[],
  "confidence": number,
  "suggested_follow_up": "Context-aware follow-up (e.g. about Powell, Fed, topic on screen) — NOT generic 'What's coming up next?'",
  "location_entities": []
}}
Extract location_entities: cities/towns/regions from context for weather links. Use [] if none."""

    if re.search(r"what'?s on screen|describe.*screen|what do you see", q):
        return f"""Question: {req['user_message']}
{recent_block}Current scene: {current_scene}
Current on-screen text: {current_ocr}
Persistent on-screen text: {persistent_ocr}
Recent scenes: {recent_scenes}
{seg_block}Transcript: {transcript}
Channel: {channel}

Prioritize:
1. current scene
2. current on-screen text
3. persistent on-screen text
4. active segment summary (when present)
5. transcript
6. channel metadata

Return JSON:
{{
  "primary_answer": string,
  "supporting_points": string[],
  "confidence": number,
  "suggested_follow_up": "Context-aware follow-up (e.g. about Powell, Fed, topic on screen) — NOT generic 'What's coming up next?'",
  "location_entities": []
}}
Extract location_entities: cities/towns/regions from context for weather links. Use [] if none."""

    # whats_this_about, entity questions (What is X?), etc. — segment summary first per Spec 24.13
    return f"""Question: {req['user_message']}
{recent_block}{seg_block}Persistent on-screen text: {persistent_ocr}
Transcript: {transcript}
Current on-screen text: {current_ocr}
Current scene: {current_scene}
Channel: {channel}

Prioritize:
1. segment summary
2. active segment type
3. transcript
4. persistent on-screen text
5. current on-screen text
6. current scene

Return JSON:
{{
  "primary_answer": string,
  "supporting_points": string[],
  "confidence": number,
  "suggested_follow_up": "Context-aware follow-up (e.g. about Powell, Fed, topic on screen) — NOT generic 'What's coming up next?'",
  "location_entities": []
}}
Extract location_entities: cities/towns/regions from context for weather links. Use [] if none."""


def moments_respond(req: dict[str, Any]) -> str:
    """
    STIRR Moments Engine MVP: respond to KNOW moments (what am I watching, what's on screen, what's this about).
    P4-H13: Ad break gate per spec §5.3 — pre/mid suppress KNOW,GO,DO,BUY; post suppresses BUY only.
    """
    import time
    _start = time.perf_counter()

    user_message = (req.get("user_message") or "").strip()
    player = req.get("player") or {}
    if not user_message:
        return json.dumps({"error": "user_message required"})
    channel_id = (player.get("channel_id") or "").strip()
    if not channel_id:
        return json.dumps({"error": "player.channel_id required"})

    # P4-H13: Moment detection before gate (needed for post + BUY suppression)
    from moment import detect_moment, get_moment_prompt_addition, MOMENT_BUY, MOMENT_GO, MOMENT_DO

    player_state = {"channel_id": channel_id, "is_live": player.get("is_live", True)}
    moment = detect_moment(user_message, session={}, player_state=player_state)

    ad_break_state = player.get("ad_break_state")
    # §5.3 pre/mid: suppress KNOW, GO, DO, BUY (WATCH allowed but we return generic message for MVP)
    if ad_break_state in ("pre", "mid"):
        logger.info("moments_respond: P4-H13 ad_suppression | ad_break_state=%s moment=%s", ad_break_state, moment)
        return json.dumps({
            "moment": moment,
            "moment_confidence": 1.0,
            "primary_answer": "An ad break is in progress. Ask again when the program returns.",
            "supporting_points": [],
            "confidence": 1.0,
            "suggested_follow_up": None,
            "location_entities": [],
            "components": [{"type": "text", "content": "An ad break is in progress. Ask again when the program returns."}],
            "actions": [{"type": "ASK_FOLLOW_UP", "label": "What's this about?", "component": "ConversationalSearch"}],
            "ad_break_suppressed": True,
            "catalog_id": "stirr-intent",
        })
    # §5.3 post: suppress BUY only (avoid cannibalization of just-played ad)
    if ad_break_state == "post" and moment == MOMENT_BUY:
        logger.info("moments_respond: P4-H13 BUY suppressed post-ad | ad_break_state=post")
        return json.dumps({
            "moment": MOMENT_BUY,
            "moment_confidence": 1.0,
            "primary_answer": "Let me find that for you — one moment.",
            "supporting_points": [],
            "confidence": 1.0,
            "suggested_follow_up": "Ask again in a few seconds when we're back.",
            "location_entities": [],
            "components": [{"type": "text", "content": "Let me find that for you — one moment."}],
            "actions": [{"type": "ASK_FOLLOW_UP", "label": "Ask again in a few seconds when we're back.", "component": "ConversationalSearch"}],
            "ad_break_suppressed": True,
            "catalog_id": "stirr-intent",
        })

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set for moments_respond")
        fallback_msg = "Set GEMINI_API_KEY for full answers."
        return json.dumps({
            "moment": "KNOW",
            "moment_confidence": 0.5,
            "primary_answer": fallback_msg,
            "supporting_points": [],
            "confidence": 0.5,
            "suggested_follow_up": None,
            "location_entities": [],
            "components": [{"type": "text", "content": fallback_msg}],
            "actions": [{"type": "ASK_FOLLOW_UP", "label": "What's this about?", "component": "ConversationalSearch"}],
            "catalog_id": "stirr-intent",
        })

    perception = req.get("perception") or {}
    perception_source = perception.get("perception_source", "unknown")
    persistent_ocr = perception.get("persistent_ocr") or []
    has_persistent_ocr = len(persistent_ocr) > 0
    logger.info(
        "moments_respond: perception_source=%s | persistent_ocr=%s | transcript=%s",
        perception_source,
        "yes" if has_persistent_ocr else "no",
        "yes" if (req.get("transcript_local") or {}).get("text") or (req.get("transcript_server") or {}).get("text") else "no",
    )

    # Moment already detected above for ad gate; continue with prompt assembly
    from intent import needs_web_retrieval

    moment_prompt = get_moment_prompt_addition(moment)
    logger.info(f"moments_respond: moment={moment}")

    # P4-H9 + P4-H10: Web retrieval; moment GO/DO/BUY → force web
    use_web = needs_web_retrieval(user_message) or moment in (MOMENT_GO, MOMENT_DO, MOMENT_BUY)

    user_prompt = _moments_select_prompt(req)
    if moment_prompt:
        user_prompt += moment_prompt
    if use_web:
        user_prompt += "\n\nWeb search is enabled. Use real-time web results to enrich your answer (people, places, weather, traffic, how-to). Combine on-screen context with web data when both are relevant."

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig, Tool, GoogleSearch

        client = genai.Client(api_key=api_key)
        model = os.getenv("LITELLM_MODEL", "gemini-2.5-flash").replace("gemini/", "")

        gen_config = (
            GenerateContentConfig(
                system_instruction=MOMENTS_SYSTEM_PROMPT,
                tools=[Tool(google_search=GoogleSearch())],
            )
            if use_web
            else GenerateContentConfig(system_instruction=MOMENTS_SYSTEM_PROMPT)
        )
        if use_web:
            logger.info("moments_respond: P4-H9 using Google Search grounding")

        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=gen_config,
        )
        raw = (getattr(response, "text", None) or str(response) or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        data = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            if start >= 0:
                depth, end = 0, start
                for i, c in enumerate(raw[start:], start):
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
                if depth == 0:
                    try:
                        data = json.loads(raw[start : end + 1])
                    except json.JSONDecodeError:
                        pass

        if not data:
            raise json.JSONDecodeError("No valid JSON", raw, 0)

        primary = data.get("primary_answer") or data.get("answer", raw[:500])
        confidence = float(data.get("confidence", 0.8))
        locs = data.get("location_entities")
        if not isinstance(locs, list):
            locs = []
        locs = [str(x).strip() for x in locs if x and str(x).strip() and len(str(x)) < 50]
        suggested = data.get("suggested_follow_up")
        supporting = data.get("supporting_points") or []

        # P4-H14: MomentsResponse contract — components, actions, moment_confidence
        chip_items: list[str] = []
        if suggested and isinstance(suggested, str) and suggested.strip():
            chip_items.append(suggested.strip())
        for loc in locs:
            chip_items.append(f"What's the weather in {loc}?")
        components: list[dict[str, Any]] = [
            {"type": "text", "content": primary},
        ]
        if chip_items:
            components.append({"type": "chipRow", "items": chip_items[:6]})

        # P4-H15: Actions include component label per spec §6
        actions_list: list[dict[str, Any]] = []
        if suggested and isinstance(suggested, str) and suggested.strip():
            actions_list.append({
                "type": "ASK_FOLLOW_UP",
                "label": suggested.strip()[:80],
                "component": "ConversationalSearch",
            })
        for loc in locs[:3]:
            actions_list.append({"type": "WEATHER_LINK", "label": f"Weather in {loc}", "component": "WeatherWidget"})
        if not actions_list:
            actions_list.append({
                "type": "ASK_FOLLOW_UP",
                "label": "What's this about?",
                "component": "ConversationalSearch",
            })

        _latency_ms = (time.perf_counter() - _start) * 1000
        logger.info(
            "moments_respond: latency_ms=%.0f | confidence=%.2f | location_entities=%s",
            _latency_ms,
            confidence,
            locs[:3] if locs else "[]",
        )
        return json.dumps({
            "moment": moment,
            "moment_confidence": confidence,
            "primary_answer": primary,
            "supporting_points": supporting,
            "confidence": confidence,
            "suggested_follow_up": suggested,
            "location_entities": locs,
            "components": components,
            "actions": actions_list,
            "catalog_id": "stirr-intent",
        })
    except Exception as e:
        logger.warning(f"moments_respond failed: {e}", exc_info=True)
        err_msg = f"Error: {str(e)[:80]}"
        return json.dumps({
            "moment": "KNOW",
            "moment_confidence": 0.5,
            "primary_answer": err_msg,
            "supporting_points": [],
            "confidence": 0.5,
            "suggested_follow_up": None,
            "location_entities": [],
            "components": [{"type": "text", "content": err_msg}],
            "actions": [{"type": "ASK_FOLLOW_UP", "label": "What's this about?", "component": "ConversationalSearch"}],
            "catalog_id": "stirr-intent",
        })
