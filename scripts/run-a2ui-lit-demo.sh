#!/usr/bin/env bash
# Run A2UI Lit client connected to STIRR agent at http://localhost:10002
# Requires: stirr-a2ui agent running (python3 run_server.py) in another terminal

set -e
A2UI_REPO="${A2UI_REPO:-$HOME/Projects/a2ui}"
STIRR_AGENT_URL="${STIRR_AGENT_URL:-http://localhost:10002}"

echo "A2UI Lit Demo — STIRR Agent"
echo "Agent URL: $STIRR_AGENT_URL"
echo ""

# Clone a2ui if needed
if [[ ! -d "$A2UI_REPO" ]]; then
  echo "Cloning google/a2ui..."
  git clone --depth 1 https://github.com/google/a2ui.git "$A2UI_REPO"
fi

cd "$A2UI_REPO/samples/client/lit"

# Install and build
echo "Installing dependencies..."
npm install
echo "Building renderer..."
npm run build:renderer 2>/dev/null || true

# Run shell only (agent must be running separately on port 10002)
# The A2UI shell connects to localhost:10002 by default (same as restaurant demo)
echo ""
echo "Starting A2UI Lit shell..."
echo "Ensure STIRR agent is running: cd stirr-a2ui/agent && python3 run_server.py"
echo "Shell connects to $STIRR_AGENT_URL (default: http://localhost:10002)"
echo ""
cd shell && npm run dev
