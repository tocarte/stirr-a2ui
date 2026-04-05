#!/bin/bash
# Run STIRR A2UI demo locally
# Usage: ./run-a2ui-demo.sh
# Or: bash run-a2ui-demo.sh

set -e

# Fix "too many open files" after macOS updates
ulimit -n 10240 2>/dev/null || true

echo "=== STIRR A2UI Demo ==="
echo ""

# 1. Start agent (query-only mode — no GEMINI_API_KEY needed)
echo "Starting agent on http://localhost:10002..."
cd "$(dirname "$0")/stirr-a2ui/agent"
python3 run_server.py --query-only --port 10002 &
AGENT_PID=$!
cd - > /dev/null

# Wait for agent to be ready
sleep 2
if ! curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:10002/query \
  -H "Content-Type: application/json" -d '{"query":"test"}' | grep -q 200; then
  echo "Agent may still be starting..."
fi

echo "Agent running (PID $AGENT_PID)"
echo ""

# 2. Start frontend (WATCHPACK_WATCHER_LIMIT fixes EMFILE on macOS)
echo "Starting frontend on http://localhost:3000..."
cd "$(dirname "$0")/stirr-platform-nextgen/frontend"
WATCHPACK_WATCHER_LIMIT=20 npm run dev &
FRONTEND_PID=$!
cd - > /dev/null

echo ""
echo "=== Demo ready ==="
echo "  Frontend:  http://localhost:3000/a2ui-demo"
echo "  Agent:     http://localhost:10002"
echo ""
echo "Try: 'Show me breaking news from Dallas' | 'Find me something to watch tonight'"
echo ""
echo "Press Ctrl+C to stop both processes."
echo ""

# Trap Ctrl+C to kill both
trap "kill $AGENT_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
