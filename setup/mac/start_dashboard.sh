#!/usr/bin/env bash
# ContextBridge — Start dashboard only (macOS)

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
PYTHON="${PYTHON:-python3}"
mkdir -p "$LOG_DIR"

echo "Starting ContextBridge Dashboard on http://127.0.0.1:8795 ..."
nohup "$PYTHON" "$CB_DIR/dashboard_server.py" > "$LOG_DIR/dashboard.log" 2>&1 &
DASH_PID=$!
echo "$DASH_PID" > "$LOG_DIR/dashboard.pid"

sleep 2
open "http://127.0.0.1:8795"

echo "Dashboard started. PID: $DASH_PID"
echo "Log: usage/logs/dashboard.log"
echo ""
