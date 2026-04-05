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
- Tools: search_content (VODLIX API: v2/search, v2/videos/list)

## Environment Variables

- **Never hardcode credentials** — use `from stirr_config import config`
- **Never commit `.env`** — only `.env.example`
- Call `config.require("var1", "var2")` at script top to fail fast on missing vars
- When adding a new var: update `.env.example` and `stirr_config.py`
- Full reference: `stirr-control/docs/ENV-MANAGEMENT.md`
