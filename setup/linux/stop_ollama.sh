#!/usr/bin/env bash
# ContextBridge — Stop Ollama + unload models from VRAM (Linux)

echo "============================================="
echo " Stopping Ollama"
echo "============================================="
echo ""

# Check if Ollama is running
if ! lsof -ti tcp:11434 &>/dev/null; then
    echo "Ollama is not running on port 11434."
    echo ""
    exit 0
fi

# Unload models from VRAM via API
echo "Unloading models from VRAM..."
MODELS=$(curl -s http://localhost:11434/api/ps 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for m in data.get('models', []):
        print(m['name'])
except:
    pass
" 2>/dev/null || true)

if [ -n "$MODELS" ]; then
    while IFS= read -r MODEL; do
        echo "  Unloading: $MODEL"
        curl -s -X POST http://localhost:11434/api/generate \
            -H "Content-Type: application/json" \
            -d "{\"model\":\"$MODEL\",\"keep_alive\":0}" > /dev/null 2>&1 || true
    done <<< "$MODELS"
else
    echo "  No models loaded in VRAM."
fi

echo ""
echo "Stopping Ollama process..."
pkill -f "ollama serve" 2>/dev/null || true
pkill -f "ollama" 2>/dev/null || true

sleep 2

# Verify
if lsof -ti tcp:11434 &>/dev/null; then
    echo "WARNING: Port 11434 still in use. Try: sudo pkill -9 ollama"
else
    echo "SUCCESS: Ollama stopped. VRAM released."
fi

echo ""
echo "============================================="
