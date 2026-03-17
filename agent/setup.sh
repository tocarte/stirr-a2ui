#!/usr/bin/env bash
# Initialize the STIRR Content Agent: install deps, create .env from example.
# Run from anywhere: ~/Projects/stirr-a2ui/agent/setup.sh

set -e
cd "$(dirname "$0")"

echo "Installing dependencies..."
uv sync 2>/dev/null || pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env — edit with your GEMINI_API_KEY and VODLIX_* credentials"
else
  echo ".env exists"
fi

echo ""
echo "Ready. Run: uv run python run_server.py --query-only --port 10002"
