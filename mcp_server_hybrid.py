from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(project_root.parent))
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

    _validate_startup(project_root)
    _warm_semantic_rag_if_configured()

    from mcp_tools.hybrid_server import run_server
    run_server()
    return 0


def _validate_startup(project_root: Path) -> None:
    """Fail fast at startup with a clear message rather than a cryptic mid-request error."""
    errors: list[str] = []

    # --- Required env vars ---
    port = os.environ.get("CONTEXT_BRIDGE_PORT", "").strip()
    if not port:
        errors.append("CONTEXT_BRIDGE_PORT is not set. Start the server via start_Context_Bridge.bat.")
    elif not port.isdigit():
        errors.append(f"CONTEXT_BRIDGE_PORT='{port}' is not a valid port number.")

    transport = os.environ.get("CONTEXT_BRIDGE_TRANSPORT", "").strip().lower()
    if transport not in ("sse", "stdio", ""):
        errors.append(f"CONTEXT_BRIDGE_TRANSPORT='{transport}' is unknown. Use 'sse' or 'stdio'.")

    # --- Config file ---
    config_name = (os.environ.get("CONTEXT_BRIDGE_CONFIG") or "config.hybrid.json").strip() or "config.hybrid.json"
    config_path = project_root / config_name
    if not config_path.exists():
        errors.append(f"Config file not found: {config_path}  (CONTEXT_BRIDGE_CONFIG='{config_name}')")

    # --- Vector paths (only required when not in keyword mode) ---
    # We check keyword mode by peeking at the config — but only if the config exists.
    is_keyword_mode = False
    if config_path.exists():
        try:
            import json
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            rag = raw.get("settings", {}).get("rag") or {}
            mode = str(rag.get("default_mode") or "hybrid").strip().lower()
            is_keyword_mode = rag.get("enabled") is False or mode == "keyword"
        except Exception:
            pass  # Config parse errors are caught properly by load_config later

    if not is_keyword_mode:
        vector_meta_raw = (os.environ.get("CONTEXT_BRIDGE_VECTOR_META") or "").strip()
        vector_index_raw = (os.environ.get("CONTEXT_BRIDGE_VECTOR_INDEX") or "").strip()

        vector_meta = Path(vector_meta_raw) if vector_meta_raw else project_root / "data" / "vector_meta.json"
        vector_index = Path(vector_index_raw) if vector_index_raw else project_root / "data" / "vector_index.jsonl"

        if not vector_meta.exists():
            errors.append(
                f"Vector manifest not found: {vector_meta}\n"
                f"  Run the indexer to regenerate it, or switch to keyword mode."
            )
        if not vector_index.exists():
            errors.append(
                f"Vector index not found: {vector_index}\n"
                f"  Run the indexer to regenerate it, or switch to keyword mode."
            )

    # --- Report ---
    mode_label = "keyword" if is_keyword_mode else config_name.replace("config.", "").replace(".json", "")
    print(f"[ContextBridge] Starting — mode={mode_label}, config={config_name}, port={port or '(stdio)'}", file=sys.stderr)

    # --- Embedding backend truth (read from manifest, not from config/env) ---
    if not is_keyword_mode:
        vector_meta_raw = (os.environ.get("CONTEXT_BRIDGE_VECTOR_META") or "").strip()
        vector_meta = Path(vector_meta_raw) if vector_meta_raw else project_root / "data" / "vector_meta.json"
        if vector_meta.exists():
            try:
                import json as _json
                meta = _json.loads(vector_meta.read_text(encoding="utf-8"))
                _backend = meta.get("embedding_backend", "unknown")
                _model = meta.get("embedding_model", "unknown")
                _dims = meta.get("dimensions", "?")
                print(f"[ContextBridge] Embedding backend : {_backend}", file=sys.stderr)
                print(f"[ContextBridge] Embedding model   : {_model} ({_dims} dims)", file=sys.stderr)
                print(f"[ContextBridge] Vector index      : {vector_meta.name.replace('vector_meta', 'vector_index').replace('.json', '.jsonl')}", file=sys.stderr)
            except Exception:
                print("[ContextBridge] Embedding backend : (could not read manifest)", file=sys.stderr)

    if errors:
        print("[ContextBridge] STARTUP ERRORS — server will not start:", file=sys.stderr)
        for err in errors:
            print(f"  ✗ {err}", file=sys.stderr)
        sys.exit(1)

    print(f"[ContextBridge] Startup validation passed.", file=sys.stderr)


def _warm_semantic_rag_if_configured() -> None:
    vector_meta = (os.environ.get("CONTEXT_BRIDGE_VECTOR_META") or "").strip()
    if "semantic" not in vector_meta.lower():
        return
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        from context_bridge.rag.embeddings import EmbeddingRequest, create_backend
        from context_bridge.rag.vector_store import read_manifest

        manifest = read_manifest(Path(vector_meta))
        if manifest is None:
            return
        backend = create_backend(manifest.embedding_backend, manifest.embedding_model)
        backend.embed(EmbeddingRequest(texts=["warmup"], model=manifest.embedding_model, dimensions=manifest.dimensions))


if __name__ == "__main__":
    raise SystemExit(main())
