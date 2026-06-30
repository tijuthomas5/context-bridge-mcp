#!/usr/bin/env bash
# ContextBridge — Start Ollama and warm up the configured model (macOS)

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
DEFAULT_MODEL="qwen2.5-coder:7b"

# Read model from config — falls back to default
MODEL=$("$PYTHON" -c "
import json, sys
try:
    c = json.load(open('$CB_DIR/config.hybrid.json'))
    print(c['pipeline']['analysis_stage']['model'])
except Exception:
    print('$DEFAULT_MODEL')
" 2>/dev/null || echo "$DEFAULT_MODEL")

echo ""

# Check if Ollama is already running
if lsof -ti tcp:11434 &>/dev/null; then
    echo "Ollama is already running on port 11434."
else
    echo "Starting Ollama..."
    ollama serve &>/dev/null &
    echo "Waiting for Ollama to start..."
    sleep 4
fi

echo "Warming up model: $MODEL"
echo "(This may take a minute on first load)"
echo ""
ollama run "$MODEL" /bye

echo ""
echo "Ollama is ready."
echo "  Model : $MODEL"
echo "  API   : http://localhost:11434"
echo ""
echo "You can now run start_context_bridge.sh to start ContextBridge."
echo ""
