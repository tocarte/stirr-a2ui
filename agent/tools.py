# Copyright 2025 STIRR / Thinking Media
# Licensed under the Apache License, Version 2.0

"""Tools for the STIRR content agent. Mock data for prototype; replace with VODLIX API later."""

import json
import logging
from typing import Any

from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


def _search_impl(query: str, limit: int = 10) -> list[dict[str, Any]]:
    # Mock data for P4-C prototype
    mock_items = [
        {
            "id": "7707",
            "title": "Notorious",
            "genre": "Retro Classics",
            "image_url": "https://via.placeholder.com/320x180?text=Notorious",
            "description": "Alfred Hitchcock classic. Cary Grant, Ingrid Bergman.",
        },
        {
            "id": "7937",
            "title": "Lifeboat",
            "genre": "Retro Classics",
            "image_url": "https://via.placeholder.com/320x180?text=Lifeboat",
            "description": "Hitchcock maritime survival film.",
        },
        {
            "id": "7939",
            "title": "Shadow of a Doubt",
            "genre": "Retro Classics",
            "image_url": "https://via.placeholder.com/320x180?text=Shadow+of+a+Doubt",
            "description": "Psychological thriller. Visiting family suspense.",
        },
        {
            "id": "8057",
            "title": "Homicidal",
            "genre": "Cult SciFi Horror",
            "image_url": "https://via.placeholder.com/320x180?text=Homicidal",
            "description": "William Castle shocker. Shocking movie ending.",
        },
        {
            "id": "7905",
            "title": "Spellbound",
            "genre": "Retro Classics",
            "image_url": "https://via.placeholder.com/320x180?text=Spellbound",
            "description": "Hitchcock with Salvador Dali dream sequences.",
        },
    ]
    # Simple filter by query (case-insensitive)
    q = query.lower()
    results = [i for i in mock_items if q in i["title"].lower() or q in i["genre"].lower() or q in i["description"].lower()]
    return results[:limit] if results else mock_items[:limit]


def search_content(query: str, tool_context: ToolContext, limit: int = 10) -> str:
    """
    Search STIRR content by query. Returns JSON list of items for ContentShelf.
    Prototype uses mock data; production will call VODLIX API.
    """
    logger.info(f"--- TOOL CALLED: search_content (query={query}, limit={limit}) ---")
    items = _search_impl(query, limit)
    logger.info(f" - Found {len(items)} items")
    return json.dumps({"items": items})
