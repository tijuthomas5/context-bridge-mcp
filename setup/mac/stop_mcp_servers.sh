#!/usr/bin/env bash
# ContextBridge — Stop MCP + Dashboard servers (macOS)

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

echo "Stopping ContextBridge servers..."

stop_port() {
    local PORT=$1
    local PIDS
    PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "  Killing PID(s) on port $PORT: $PIDS"
        echo "$PIDS" | xargs kill -9 2>/dev/null || true
    else
        echo "  Nothing running on port $PORT"
    fi
}

stop_port 8755
stop_port 8795

# Clean up PID files
rm -f "$LOG_DIR/mcp_server.pid" "$LOG_DIR/dashboard.pid"

echo ""
echo "Done. Ports 8755 and 8795 are now free."
echo ""
