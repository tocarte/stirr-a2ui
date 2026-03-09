# stirr-a2ui

A2UI catalog, A2A agent backend, and STIRR component spec. Agent-generated UI for streaming content discovery.

## Structure

- `agent/` — Python A2A agent (Gemini, google-adk, a2ui-agent)
- `catalog/` — STIRR A2UI catalog (ContentShelf, ConversationalSearch)
- `docs/` — Setup, integration

## Control Plane

[stirr-control](https://github.com/tocarte/stirr-control) — architecture/a2ui-overview.md

## Conventions

- Python 3.13+, uv
- `GEMINI_API_KEY` required
- Tools: search_content (mock; VODLIX later)
