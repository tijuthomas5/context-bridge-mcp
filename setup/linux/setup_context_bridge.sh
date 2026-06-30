#!/usr/bin/env bash
# ContextBridge — One-click setup (Linux)
# Installs dependencies, builds index, and prepares CB for first run.

# Locate CB root dynamically — works regardless of where this script is placed
_S="$(cd "$(dirname "$0")" && pwd)"
while [ ! -f "$_S/mcp_server_hybrid.py" ]; do
    _P="$(dirname "$_S")"
    if [ "$_P" = "$_S" ]; then echo "ERROR: Cannot find ContextBridge root" >&2; exit 1; fi
    _S="$_P"
done
CB_DIR="$_S"
ROOT="$(dirname "$CB_DIR")"
PYTHON="${PYTHON:-python3}"

echo ""
echo "ContextBridge setup started..."
echo "Workspace: $ROOT"
echo "Please wait. Index and semantic build steps can take a few minutes."
echo ""

cd "$ROOT"
"$PYTHON" context_bridge/scripts/setup_context_bridge.py "$@"
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "ContextBridge setup completed successfully."
else
    echo "ContextBridge setup failed with exit code $EXIT_CODE."
fi
echo ""
exit $EXIT_CODE
