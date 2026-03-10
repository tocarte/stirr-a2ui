#!/usr/bin/env python3
# Copyright 2025 STIRR / Thinking Media
# Licensed under the Apache License, Version 2.0

"""
STIRR Content Agent — A2A agent for ConversationalSearch + ContentShelf.

Run: uv run python -m stirr_content_agent
Requires: GEMINI_API_KEY
"""

import asyncio
import logging
import os

from a2a.types import AgentCapabilities, AgentCard, AgentSkill, Part, TextPart
from a2ui.a2a import get_a2ui_agent_extension, parse_response_to_parts
from a2ui.core.schema.constants import A2UI_CLOSE_TAG, A2UI_OPEN_TAG, VERSION_0_8
from a2ui.core.parser.parser import parse_response
from dotenv import load_dotenv
from google.adk.agents.llm_agent import LlmAgent
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from prompt_builder import ROLE_DESCRIPTION, UI_DESCRIPTION, get_schema_manager, get_text_prompt
from tools import get_breaking_news, get_chapters, search_content

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LITELLM_MODEL = os.getenv("LITELLM_MODEL", "gemini/gemini-2.5-flash")


def _build_agent(use_ui: bool):
    schema_manager = get_schema_manager() if use_ui else None
    instruction = (
        schema_manager.generate_system_prompt(
            role_description=ROLE_DESCRIPTION,
            ui_description=UI_DESCRIPTION,
            include_schema=True,
            include_examples=True,
            validate_examples=True,
        )
        if use_ui
        else get_text_prompt()
    )
    return LlmAgent(
        model=LiteLlm(model=LITELLM_MODEL),
        name="stirr_content_agent",
        description="STIRR content discovery: search and browse streaming content.",
        instruction=instruction,
        tools=[search_content, get_breaking_news, get_chapters],
    )


class StirrContentAgent:
    """A2A agent for STIRR content discovery (ConversationalSearch, ContentShelf)."""

    def __init__(self, base_url: str = "http://localhost:8000", use_ui: bool = True):
        self.base_url = base_url
        self.use_ui = use_ui
        self._schema_manager = get_schema_manager() if use_ui else None
        self._agent = _build_agent(use_ui)
        self._runner = Runner(
            app_name=self._agent.name,
            agent=self._agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
        )

    def get_agent_card(self) -> AgentCard:
        extensions = []
        if self._schema_manager:
            extensions.append(
                get_a2ui_agent_extension(
                    self._schema_manager.accepts_inline_catalogs,
                    self._schema_manager.supported_catalog_ids,
                )
            )
        capabilities = AgentCapabilities(streaming=True, extensions=extensions)
        return AgentCard(
            name="STIRR Content Agent",
            description="Search and discover streaming content. ConversationalSearch + ContentShelf.",
            url=self.base_url,
            version="0.1.0",
            default_input_modes=["text", "text/plain"],
            default_output_modes=["text", "text/plain"],
            capabilities=capabilities,
            skills=[
                AgentSkill(
                    id="search_content",
                    name="Search Content",
                    description="Search STIRR content by query (title, genre, etc.)",
                    tags=["content", "search"],
                    examples=["Find Hitchcock movies", "Something to watch tonight", "Classic films"],
                ),
                AgentSkill(
                    id="get_breaking_news",
                    name="Breaking News",
                    description="Get breaking news / live channels for a location (e.g. Dallas)",
                    tags=["news", "live"],
                    examples=["Breaking news from Dallas", "Show me Dallas news"],
                ),
                AgentSkill(
                    id="get_chapters",
                    name="Chapter Navigation",
                    description="Get chapters for a documentary or long-form video",
                    tags=["chapters", "documentary"],
                    examples=["Show me chapters", "I'm watching a documentary, show chapters"],
                ),
            ],
        )

    async def stream(self, query: str, session_id: str):
        """Stream agent response. Yields A2A events."""
        session = await self._runner.session_service.get_session(
            app_name=self._agent.name,
            user_id="stirr_user",
            session_id=session_id,
        )
        if session is None:
            session = await self._runner.session_service.create_session(
                app_name=self._agent.name,
                user_id="stirr_user",
                state={},
                session_id=session_id,
            )

        current_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=query)],
        )

        async for event in self._runner.run_async(
            user_id="stirr_user",
            session_id=session.id,
            new_message=current_message,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                text = "\n".join(p.text for p in event.content.parts if p.text)
                if self.use_ui and text:
                    try:
                        parts = parse_response_to_parts(text, fallback_text="Here are the results.")
                        yield {"is_task_complete": True, "parts": parts}
                    except Exception:
                        yield {
                            "is_task_complete": True,
                            "parts": [Part(root=TextPart(text=text))],
                        }
                else:
                    yield {
                        "is_task_complete": True,
                        "parts": [Part(root=TextPart(text=text or "No results."))],
                    }
                return
            else:
                yield {"is_task_complete": False, "updates": "Searching content..."}


def main():
    """Run as A2A server. Use a2a-sdk server or similar."""
    from a2a.server import run_server

    agent = StirrContentAgent(use_ui=True)
    # Minimal server entry — adapt to your A2A server setup
    print("STIRR Content Agent ready. Use with A2UI Lit client.")
    print("Run: cd /path/to/a2ui/samples/client/lit && npm run demo:all")
    print("Then point the demo to this agent URL (see A2UI docs).")


if __name__ == "__main__":
    main()
