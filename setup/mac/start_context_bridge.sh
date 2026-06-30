#!/usr/bin/env bash
# ContextBridge — Main Start Script (macOS)
# Starts the MCP server + dashboard in the background.
# Logs are written to context_bridge/usage/logs/

set -euo pipefail

# Resolve paths dynamically — works from any directory
# Locate CB root dynamically — works regardless of where this script is placed
_S="$(cd "$(dirname "$0")" && pwd)"
while [ ! -f "$_S/mcp_server_hybrid.py" ]; do
    _P="$(dirname "$_S")"
    if [ "$_P" = "$_S" ]; then echo "ERROR: Cannot find ContextBridge root" >&2; exit 1; fi
    _S="$_P"
done
CB_DIR="$_S"
ROOT="$(dirname "$CB_DIR")"
LOG_DIR="$CB_DIR/usage/logs"
mkdir -p "$LOG_DIR"

PYTHON="${PYTHON:-python3}"
PORT=8755

echo ""
echo "Select ContextBridge mode:"
echo "  1. Hybrid   (keyword + vector)  [recommended]"
echo "  2. Semantic (vector only)"
echo "  3. Keyword  (keyword only)"
echo ""
read -r -p "Enter 1, 2 or 3 (default: 1): " CHOICE

# Set config and vector paths based on mode
CONTEXT_BRIDGE_CONFIG="config.hybrid.json"
MODE="Hybrid"
CB_VECTOR_INDEX="$CB_DIR/data/vector_index.jsonl"
CB_VECTOR_META="$CB_DIR/data/vector_meta.json"

if [ "${CHOICE:-1}" = "2" ]; then
    CONTEXT_BRIDGE_CONFIG="config.semantic.json"
    CB_VECTOR_INDEX="$CB_DIR/data/vector_index.semantic.jsonl"
    CB_VECTOR_META="$CB_DIR/data/vector_meta.semantic.json"
    MODE="Semantic"
elif [ "${CHOICE:-1}" = "3" ]; then
    CONTEXT_BRIDGE_CONFIG="config.json"
    CB_VECTOR_INDEX=""
    CB_VECTOR_META=""
    MODE="Keyword"
fi

# Read profile dynamically from config — no hardcoding
CONTEXT_BRIDGE_PROFILE=$("$PYTHON" -c "
import json, sys
try:
    c = json.load(open('$CB_DIR/config.hybrid.json'))
    print(c.get('runtime', {}).get('project_profile', 'default'))
except Exception:
    print('default')
" 2>/dev/null || echo "default")

# API key — set in env or leave placeholder
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-YOUR_API_KEY_HERE}"

# Export env vars for MCP server
export CONTEXT_BRIDGE_CONFIG
export CONTEXT_BRIDGE_PROFILE
export CONTEXT_BRIDGE_TRANSPORT=sse
export CONTEXT_BRIDGE_PORT=$PORT
export ANTHROPIC_API_KEY

[ -n "$CB_VECTOR_INDEX" ] && export CONTEXT_BRIDGE_VECTOR_INDEX="$CB_VECTOR_INDEX"
[ -n "$CB_VECTOR_META" ]  && export CONTEXT_BRIDGE_VECTOR_META="$CB_VECTOR_META"

cd "$CB_DIR"

echo ""
echo "Starting ContextBridge [$MODE] on http://127.0.0.1:$PORT/sse ..."
nohup "$PYTHON" "$CB_DIR/mcp_server_hybrid.py" > "$LOG_DIR/mcp_server.log" 2>&1 &
MCP_PID=$!
echo "$MCP_PID" > "$LOG_DIR/mcp_server.pid"
echo "  MCP server PID : $MCP_PID"
echo "  Log            : usage/logs/mcp_server.log"

echo ""
echo "Starting dashboard on http://127.0.0.1:8795 ..."
nohup "$PYTHON" "$CB_DIR/dashboard_server.py" > "$LOG_DIR/dashboard.log" 2>&1 &
DASH_PID=$!
echo "$DASH_PID" > "$LOG_DIR/dashboard.pid"
echo "  Dashboard PID  : $DASH_PID"
echo "  Log            : usage/logs/dashboard.log"

sleep 2
open "http://127.0.0.1:8795"

echo ""
echo "Both servers started."
echo "  MCP server : http://127.0.0.1:$PORT/sse"
echo "  Dashboard  : http://127.0.0.1:8795"
echo "  Profile    : $CONTEXT_BRIDGE_PROFILE"
echo "  Mode       : $MODE"
echo ""
echo "To stop: run stop_mcp_servers.sh"
echo ""
