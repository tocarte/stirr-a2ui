# Copyright 2025 STIRR / Thinking Media
# Licensed under the Apache License, Version 2.0

"""
P4-H10: Moment detection layer — runs before LLM.
Maps query + session + playerState → StirrMoment (WATCH, KNOW, GO, DO, BUY).
See stirr-control/architecture/stirr-moments-inference-model.md §3.
"""

import re
from typing import Any, Dict, Optional

# STIRR Moment taxonomy
MOMENT_WATCH = "WATCH"
MOMENT_KNOW = "KNOW"
MOMENT_GO = "GO"
MOMENT_DO = "DO"
MOMENT_BUY = "BUY"

# GO: navigation, directions, where to watch
_GO_PATTERNS = re.compile(
    r"(where is (this|that)|how do i get (there|to)|directions|"
    r"what channel has (this|that)|where can i watch (this|that)|"
    r"how do i visit|where'?s (this|that) (bar|restaurant|place)|"
    r"get directions|map to|navigate to)",
    re.I,
)

# DO: how-to, instructions, actions
_DO_PATTERNS = re.compile(
    r"(how (do i|to|can i)|how'?d you|steps to|how do you|"
    r"how do i (make|cook|get tickets|watch this later)|"
    r"instructions? for|recipe for)",
    re.I,
)

# BUY: transactional, commerce, booking
_BUY_PATTERNS = re.compile(
    r"(where (can i|to) buy|best price|where to get|buy .+ online|"
    r"can i (book|reserve)|what restaurant is this|book (a )?table|"
    r"order (from|online)|purchase)",
    re.I,
)

# WATCH: discovery, recommendations, what to watch
_WATCH_PATTERNS = re.compile(
    r"(what (else )?can i watch|recommend|what'?s next|what should i watch|"
    r"show me more|similar content|what'?s on (next|after)|"
    r"other options|suggest some|give me some|list some|what'?s coming up)",
    re.I,
)


def detect_moment(
    query: str,
    session: Optional[Dict[str, Any]] = None,
    player_state: Optional[Dict[str, Any]] = None,
) -> str:
    """
    P4-H10: Detect StirrMoment from query, session, and player state.
    Runs before LLM. Returns one of: WATCH, KNOW, GO, DO, BUY.

    Session and player_state are optional; used for future signals
    (dwell time, content type, live vs VOD).
    """
    q = (query or "").strip().lower()
    if not q:
        return MOMENT_KNOW

    # Order matters: more specific moments first
    if _BUY_PATTERNS.search(q):
        return MOMENT_BUY
    if _GO_PATTERNS.search(q):
        return MOMENT_GO
    if _DO_PATTERNS.search(q):
        return MOMENT_DO
    if _WATCH_PATTERNS.search(q):
        return MOMENT_WATCH

    # Default: KNOW (understanding content — primary LLM use case)
    return MOMENT_KNOW


def get_moment_prompt_addition(moment: str) -> str:
    """Moment-aware prompt addition per stirr-moments-inference-model §8."""
    if moment == MOMENT_GO:
        return (
            " The user wants navigation/directions. Extract location from context. "
            "Offer directions or map when relevant. End with a CTA like 'Want directions?'"
        )
    if moment == MOMENT_DO:
        return (
            " The user wants instructions/how-to. Provide step-by-step guidance. "
            "Use web search when needed for recipes, procedures, etc."
        )
    if moment == MOMENT_BUY:
        return (
            " The user is in a transactional mindset. Identify product/place from context. "
            "Offer booking or purchase path when relevant."
        )
    if moment == MOMENT_WATCH:
        return (
            " The user wants recommendations. List specific titles from context. "
            "Be discovery-focused."
        )
    # KNOW: no extra addition (default behavior)
    return ""
