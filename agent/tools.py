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
from google.adk.tools.tool_context import ToolContext

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
    """Map VODLIX video to ContentShelf item format."""
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

    return {
        "id": video_id,
        "title": video.get("title", "Untitled"),
        "genre": genre,
        "image_url": image_url or "https://via.placeholder.com/320x180?text=No+Image",
        "description": (video.get("description") or "")[:200],
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
