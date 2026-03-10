# stirr-a2ui

A2UI catalog, A2A agent backend, and STIRR component spec for agent-generated streaming UI.

**Control plane:** [stirr-control](https://github.com/tocarte/stirr-control) — see `architecture/a2ui-overview.md`

## Structure

```
stirr-a2ui/
├── agent/           # Python A2A agent (Gemini-powered)
│   ├── stirr_content_agent.py
│   ├── tools.py     # VODLIX content search
│   └── pyproject.toml
├── catalog/         # STIRR A2UI component catalog (v0.8)
│   └── stirr_catalog.json
└── docs/            # Setup, integration notes
```

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com/apikey)
- `VODLIX_API_BASE`, `VODLIX_USERNAME`, `VODLIX_PASSWORD` for content search (same as stirr-content-tools, stirr-search-feeds)

### Run the STIRR Content Agent

```bash
cd agent
uv sync
export GEMINI_API_KEY="your-key"
export VODLIX_API_BASE="https://stirr.com/api"
export VODLIX_USERNAME="your-email"
export VODLIX_PASSWORD="your-password"
uv run python run_server.py --port 10002
```

**Tools-only mode** (no Gemini, for testing): `uv run python run_server.py --query-only --port 10002`

The agent runs as an A2A server. Connect with the [A2UI Lit client](https://github.com/google/a2ui/tree/main/samples/client/lit) or the demo in `stirr-platform-nextgen`.

### Run with A2UI Demo (stirr-platform-nextgen)

See `stirr-platform-nextgen/docs/A2UI_DEMO.md` for full setup.

## Components

**Phase 1 (implemented):**
- **ConversationalSearch** — Search input → agent returns content results as `List` of `Card`s
- **ContentShelf** — Horizontal shelf of content cards (`List` + `Card` + `Image` + `Text`)

**Phase 2–3 (catalog defined):**
- **NewsAlertBanner** — Breaking-news banner (`Card` + `Text` + `Icon`)
- **ScoreOverlay** — Sports score display (`Card` + `Text` + `Row`)
- **ChapterNav** — Chapter list for long-form content (`List` + `Button` + `Text`)

## Create GitHub Repo

To push this to GitHub:

```bash
# Create repo on GitHub (via web or gh), then:
cd stirr-a2ui
git init
git add .
git commit -m "Initial: A2UI agent + catalog for STIRR"
git remote add origin https://github.com/tocarte/stirr-a2ui.git
git push -u origin main
```

Or with GitHub CLI (after `gh auth login`):

```bash
gh repo create tocarte/stirr-a2ui --public --source=. --push
```

## License

Apache 2.0 (aligned with [google/a2ui](https://github.com/google/a2ui))
