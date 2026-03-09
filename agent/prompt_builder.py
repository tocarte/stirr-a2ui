# Copyright 2025 STIRR / Thinking Media
# Licensed under the Apache License, Version 2.0

"""Prompt builder for STIRR content agent. Generates A2UI-aware system prompt."""

from a2ui.core.schema.constants import VERSION_0_8
from a2ui.core.schema.manager import A2uiSchemaManager
from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.core.schema.common_modifiers import remove_strict_validation

ROLE_DESCRIPTION = (
    "You are a helpful STIRR content discovery assistant for a streaming platform. "
    "Your final output MUST be an A2UI UI JSON response."
)

UI_DESCRIPTION = """
- If the user searches for content (e.g., "Find Hitchcock movies", "Classic films"), use the `search_content` tool to get results, then render a ContentShelf: a horizontal List of Cards. Each Card contains Image (poster) + Text (title, genre). Bind the list to `/shelf/items` from the tool response.
- For ConversationalSearch: show a TextField for search input, then when results are returned, display them as a List of Cards (Image + Text per item).
- Use the standard A2UI components: List, Card, Image, Text, TextField, Button.
- Keep the UI minimal and focused on content discovery.
"""


def get_text_prompt() -> str:
    """Text-only fallback prompt."""
    return """
You are a helpful STIRR content discovery assistant. Your final output MUST be a text response.

1. For content search: Call the `search_content` tool with the user's query. Format the results as a clear list with title, genre, and description.
2. Be concise and helpful.
"""


def get_schema_manager():
    """Build schema manager for STIRR agent (uses BasicCatalog for Phase 1)."""
    import os
    examples_path = os.path.join(os.path.dirname(__file__), "examples")
    catalog = BasicCatalog.get_config(version=VERSION_0_8, examples_path=examples_path)
    return A2uiSchemaManager(
        VERSION_0_8,
        catalogs=[catalog],
        schema_modifiers=[remove_strict_validation],
    )
