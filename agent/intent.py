# Copyright 2025 STIRR / Thinking Media
# Licensed under the Apache License, Version 2.0

"""
Intent classifier and context assembly for STIRR multimodal chat.
Phase A: Rule-based intent detection + context subset by intent.
See stirr-control/architecture/stirr-multimodal-chat-architecture.md
"""

import re
from typing import Any, Optional

# Intent taxonomy (stirr-multimodal-chat-architecture §3)
WATCH_INTENT = "watch_intent"
ONSCREEN_INTENT = "onscreen_intent"
SEGMENT_INTENT = "segment_intent"
UTILITY_INTENT = "utility_intent"
ENTITY_INTENT = "entity_intent"
GENERAL_INTENT = "general_broadcast_intent"

# Regex patterns for rule-based classification (§4)
_WATCH_PATTERNS = re.compile(
    r"(what am i watching|what channel|is this live|what is this program|"
    r"what program|what show|what's playing|what am i viewing)",
    re.I,
)
_ONSCREEN_PATTERNS = re.compile(
    r"(what'?s on screen|describe (the )?screen|what do you see|who'?s on screen|"
    r"what'?s on the screen|describe this shot|what does the screen show)",
    re.I,
)
_SEGMENT_PATTERNS = re.compile(
    r"(what'?s this about|summarize this|what are they talking about|"
    r"what is this story|what'?s the story|what'?s this segment about|"
    r"why are they talking about|explain this segment|show me segments)",
    re.I,
)
_UTILITY_PATTERNS = re.compile(
    r"(what else can i watch|recommend|what'?s next|what should i watch|"
    r"show me more|similar content|what'?s on (next|after)|other options|"
    r"suggest some|give me some|list some|what'?s coming up)",
    re.I,
)
_ENTITY_PATTERNS = re.compile(
    r"(who is |who'?s |where is |what is |what'?s )\w+",
    re.I,
)


def classify_intent(message: str) -> str:
    """
    Classify user question into intent. Rule-based, fast, no LLM.
    Returns one of: watch_intent, onscreen_intent, segment_intent,
    utility_intent, entity_intent, general_broadcast_intent.
    """
    q = (message or "").strip().lower()
    if not q:
        return GENERAL_INTENT

    if _WATCH_PATTERNS.search(q):
        return WATCH_INTENT
    if _ONSCREEN_PATTERNS.search(q):
        return ONSCREEN_INTENT
    if _SEGMENT_PATTERNS.search(q):
        return SEGMENT_INTENT
    if _UTILITY_PATTERNS.search(q):
        return UTILITY_INTENT
    # entity_intent: "Who is X?", "Where is Y?", "What is Z?"
    # Only if it looks like a specific entity question (not generic "what is this")
    if _ENTITY_PATTERNS.search(q) and "this" not in q and "that" not in q:
        return ENTITY_INTENT

    return GENERAL_INTENT


# STIRR TV Companion system prompt (§7)
SYSTEM_PROMPT = """You are STIRR's AI-powered TV companion.

Your job is to help viewers understand what they are watching right now on STIRR, especially live local news and broadcast content.

You may be given:
- channel and station metadata
- program metadata
- transcript excerpts
- OCR / on-screen text
- visual scene summaries or frames
- UI context such as recommendations or rail items

Rules:
1. Answer as a broadcast-aware assistant, not as a generic chatbot.
2. Combine transcript, on-screen text, and visual details into one grounded answer.
3. If asked what is on screen, prioritize visual scene details and on-screen text.
4. If asked what the segment is about, prioritize lower-third text and transcript.
5. If asked what the user is watching, identify the channel/program/station first.
6. When evidence is partial, make a careful best-effort inference using "looks like" or "appears to be."
7. Do not claim certainty when the evidence is weak.
8. Do not say "the context doesn't contain the answer" if there is enough information to make a useful viewer-facing response.
9. Keep answers concise, natural, and easy to scan.
10. When helpful, include a short follow-up suggestion (weather, what's next, related viewing).

Tone: Friendly, clear, conversational, lightly polished. Avoid robotic language."""


# Intent-specific prompt additions (§5 Context Assembly)
INTENT_PROMPTS = {
    WATCH_INTENT: (
        "The user wants to know what they are watching. Focus on: channel/program name, "
        "whether it's live or replay, and a brief program description. Use channel and program metadata first."
    ),
    ONSCREEN_INTENT: (
        "The user wants to know what's on screen. Focus on: visual scene, on-screen text (lower-thirds, "
        "banners), and any visible labels. Prioritize OCR and vision data. If no frame/OCR is available, "
        "infer from program metadata and say 'Based on the program...' or 'Looks like...'"
    ),
    SEGMENT_INTENT: (
        "The user wants to know what this segment/story is about. Focus on: transcript content, "
        "lower-third text, and program context. Summarize the topic briefly. If no transcript, use "
        "program description and say 'Based on the program description...'"
    ),
    UTILITY_INTENT: (
        "The user wants recommendations, what's next, or suggestions. You MUST list specific titles by name "
        "from the 'What else to watch' section—e.g. 'Try ABC 5 - KSTP, News10NBC - WHEC, or Encore+.' "
        "Do NOT give vague answers like 'there are many channels available.' For 'what's coming up next', "
        "if no schedule is in context, say so briefly and then list other channels they can try."
    ),
    ENTITY_INTENT: (
        "The user is asking about a specific person, place, or thing. Use transcript, OCR, and "
        "program metadata. If the entity isn't in context, make a best-effort inference or say "
        "'I don't have details on that in the current context.'"
    ),
    GENERAL_INTENT: (
        "Answer as a TV companion using whatever context is available. Combine channel, program, "
        "transcript, OCR, and vision. Be helpful and concise."
    ),
}


def build_context_for_intent(
    intent: str,
    context_bundle: dict[str, Any],
) -> str:
    """
    Build a formatted context string for the given intent.
    Subsets and orders context by evidence ranking (§5, §6).
    Phase A: Only program/channel from VODLIX; OCR/vision/transcript are placeholders.
    """
    parts: list[str] = []
    session = context_bundle.get("session") or {}
    channel = context_bundle.get("channel") or {}
    program = context_bundle.get("program") or {}
    transcript = context_bundle.get("transcript") or {}
    ocr = context_bundle.get("ocr") or {}
    vision = context_bundle.get("vision") or {}
    ui_context = context_bundle.get("ui_context") or {}

    def add_section(title: str, content: str) -> None:
        if content.strip():
            parts.append(f"## {title}\n{content.strip()}")

    # For utility_intent, put recommendations FIRST so the model uses them
    recs = ui_context.get("visible_recommendations") or []
    if recs and intent == "utility_intent":
        lines = []
        for i, r in enumerate(recs[:10], 1):
            t = r.get("title", r) if isinstance(r, dict) else str(r)
            typ = r.get("type", "") if isinstance(r, dict) else ""
            suffix = f" — {typ}" if typ else ""
            lines.append(f"{i}. {t}{suffix}")
        add_section("What else to watch (REQUIRED: suggest these specific titles)", "\n".join(lines))

    # Program metadata (from VODLIX video)
    prog_lines = []
    if program.get("title"):
        prog_lines.append(f"Title: {program['title']}")
    if program.get("description"):
        prog_lines.append(f"Description: {program['description']}")
    if program.get("genre"):
        prog_lines.append(f"Genre: {program['genre']}")
    if program.get("is_live") is not None:
        prog_lines.append(f"Live: {program['is_live']}")
    if prog_lines:
        add_section("Program", "\n".join(prog_lines))

    # Channel metadata
    ch_lines = []
    if channel.get("channel_name"):
        ch_lines.append(f"Channel: {channel['channel_name']}")
    if channel.get("market"):
        ch_lines.append(f"Market: {channel['market']}")
    if channel.get("category"):
        ch_lines.append(f"Category: {channel['category']}")
    if ch_lines:
        add_section("Channel", "\n".join(ch_lines))

    # Transcript (Phase D; placeholder for now)
    trans_text = transcript.get("current_text") or transcript.get("summary", "")
    if trans_text:
        add_section("Transcript (recent)", trans_text[:500])

    # OCR / on-screen text (Phase B; placeholder)
    onscreen = ocr.get("onscreen_text") or []
    if isinstance(onscreen, list) and onscreen:
        add_section("On-screen text", "\n".join(str(t) for t in onscreen[:10]))
    elif isinstance(onscreen, str) and onscreen:
        add_section("On-screen text", onscreen)

    # Vision / scene summary (Phase C; placeholder)
    scene = vision.get("scene_summary") or vision.get("summary", "")
    if scene:
        add_section("Scene", scene)

    # UI context (recommendations) - also add for non-utility intents
    if recs and intent != "utility_intent":
        lines = []
        for i, r in enumerate(recs[:10], 1):
            t = r.get("title", r) if isinstance(r, dict) else str(r)
            typ = r.get("type", "") if isinstance(r, dict) else ""
            suffix = f" — {typ}" if typ else ""
            lines.append(f"{i}. {t}{suffix}")
        add_section("Recommendations", "\n".join(lines))

    if not parts:
        return "No context available. Use program title and description if provided elsewhere."

    return "\n\n".join(parts)


def build_minimal_context_bundle(video: Optional[dict[str, Any]]) -> dict[str, Any]:
    """
    Build a minimal context bundle from VODLIX video metadata.
    Used when only video metadata is available (Phase A).
    """
    if not video:
        return {"program": {}, "channel": {}, "transcript": {}, "ocr": {}, "vision": {}, "ui_context": {}}

    title = video.get("title", "")
    desc = video.get("description", "")
    tags = video.get("tags", "")
    is_live = video.get("content_type") == 4 or video.get("live") or video.get("live_status")
    categories = video.get("categories") or []
    genre = ", ".join(
        c.get("category_name", "") for c in categories if isinstance(c, dict) and c.get("category_name")
    ) or video.get("genre", "")

    program = {
        "title": title,
        "description": desc,
        "genre": genre,
        "tags": tags,
        "is_live": bool(is_live),
    }

    # Channel: infer from title for live (e.g. "NewsChannel 13 - WNYT")
    channel = {
        "channel_name": title if is_live else "STIRR",
        "market": "",
        "category": genre or "General",
    }

    return {
        "session": {"locale": "en-US"},
        "channel": channel,
        "program": program,
        "transcript": {},
        "ocr": {},
        "vision": {},
        "ui_context": {},
    }
