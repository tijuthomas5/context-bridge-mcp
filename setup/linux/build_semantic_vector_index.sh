#!/usr/bin/env bash
# ContextBridge — Build semantic vector index (Linux)

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

echo "Building semantic vector index..."
echo "This may take several minutes depending on codebase size."
echo ""

cd "$ROOT"
"$PYTHON" context_bridge/rag/build_vector_index.py \
    --config config.hybrid.json \
    --backend sentence-transformers \
    --model all-MiniLM-L6-v2 \
    --chunks-output context_bridge/data/vector_chunks.semantic.jsonl \
    --index-output context_bridge/data/vector_index.semantic.jsonl \
    --manifest-output context_bridge/data/vector_meta.semantic.json \
    --batch-size 32

echo ""
echo "Semantic vector index built successfully."
echo ""
