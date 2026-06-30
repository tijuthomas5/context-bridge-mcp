#!/usr/bin/env bash
# ContextBridge — Clean Python bytecode cache and LLM output cache (macOS)

# Locate CB root dynamically — works regardless of where this script is placed
_S="$(cd "$(dirname "$0")" && pwd)"
while [ ! -f "$_S/mcp_server_hybrid.py" ]; do
    _P="$(dirname "$_S")"
    if [ "$_P" = "$_S" ]; then echo "ERROR: Cannot find ContextBridge root" >&2; exit 1; fi
    _S="$_P"
done
CB_DIR="$_S"
ROOT="$(dirname "$CB_DIR")"

echo ""
echo "Cleaning ContextBridge cache..."
echo ""

# Remove all __pycache__ directories
find "$CB_DIR" -type d -name "__pycache__" | while read -r DIR; do
    echo "  Removing: $DIR"
    rm -rf "$DIR"
done

# Remove LLM prompt/output cache files
for F in "$CB_DIR/usage/last_qwen_prompt.json" "$CB_DIR/usage/last_qwen_output.json"; do
    if [ -f "$F" ]; then
        echo "  Removing: $F"
        rm -f "$F"
    fi
done

echo ""
echo "Done. Restart CB now."
echo ""
