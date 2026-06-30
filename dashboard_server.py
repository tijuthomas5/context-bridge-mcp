from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PORT = 8795
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = PROJECT_ROOT / "context_bridge" / "dashboard"
CB_SCRIPT    = PROJECT_ROOT / "context_bridge" / "mcp_server_hybrid.py"
PYTHON_EXE   = sys.executable

# Apply-model state — shared between request handler and background thread.
_apply_state: dict = {"status": "idle", "message": ""}
_apply_lock  = threading.Lock()

# Stats cache — rebuilt only when event/outcome files change.
_stats_cache: dict | None = None
_stats_cache_fp: str = ""


def _stats_fingerprint() -> str:
    """mtime+size fingerprint of all dashboard-relevant source files."""
    parts: list[str] = []
    for directory in (USAGE_DIR, USAGE_DIR / "test"):
        if not directory.exists():
            continue
        for pattern in ("events*.jsonl", "outcomes*.jsonl"):
            for path in sorted(directory.glob(pattern)):
                try:
                    s = path.stat()
                    parts.append(f"{path.name}:{s.st_mtime_ns}:{s.st_size}")
                except OSError:
                    pass
    extra_files = [
        PROJECT_ROOT / "context_bridge" / "tests" / "cb_real_world_benchmark_300.json",
        PROJECT_ROOT / "context_bridge" / "tests" / "cb_real_world_benchmark_300_audit.json",
        USAGE_DIR / "latest_code_location_eval_summary.json",
        USAGE_DIR / "latest_graphify_enrichment_report.json",
        USAGE_DIR / "latest_full_quality_suite.json",
        USAGE_DIR / "last_gap_search.json",
    ]
    for path in extra_files:
        try:
            if path.exists():
                s = path.stat()
                parts.append(f"{path.name}:{s.st_mtime_ns}:{s.st_size}")
        except OSError:
            pass
    return "|".join(parts)
USAGE_DIR = PROJECT_ROOT / "context_bridge" / "usage"
TEST_USAGE_DIR = USAGE_DIR / "test"
CONFIG_DIR = PROJECT_ROOT / "context_bridge"
sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_FILES = {
    "hybrid": CONFIG_DIR / "config.hybrid.json",
    "semantic": CONFIG_DIR / "config.semantic.json",
    "keyword": CONFIG_DIR / "config.json",
}

# Known-good baseline values. These backfill any VALUE field that arrives blank
# from the dashboard form (empty string / None), so a cleared or half-loaded form
# can never wipe critical config. Boolean toggles (enabled, auto_analyze) are NOT
# backfilled here — those are genuine user choices the user is allowed to turn off.
ANALYSIS_STAGE_DEFAULTS = {
    "provider": "ollama",
    "endpoint": "http://localhost:11434/api/generate",
    "auto_analyze_timeout_seconds": 360,
    "timeout_seconds": 360,
    "num_ctx": 8192,
    "temperature": 0.1,
    "pipeline_mode": "iterative",
    "max_gap_iterations": 2,
}
RAG_DEFAULTS = {
    "default_mode": "hybrid",
    "embedding_backend": "hash",
    "embedding_model": "all-MiniLM-L6-v2",
    "top_k_vector": 12,
    "top_k_keyword": 20,
    "protected_keyword_count": 8,
    "keyword_weight": 1,
    "vector_weight": 0.35,
    "require_scope_match": True,
    "min_vector_score": 0.0,
    "fusion_strategy": "weighted_rrf",
    "lazy_load": True,
}


def _run_apply_model(model: str) -> None:
    """Background: warm model in Ollama, stop CB, restart CB."""
    cb_port = int(os.environ.get("CONTEXT_BRIDGE_PORT", "8755"))

    # Step 1 — warm up
    with _apply_lock:
        _apply_state.update({"status": "warming_up", "message": f"Loading {model} into Ollama memory…"})
    try:
        subprocess.run(["ollama", "run", model, "/bye"], timeout=300, capture_output=True, check=False)
    except Exception as exc:
        with _apply_lock:
            _apply_state.update({"status": "error", "message": f"Warm-up failed: {exc}"})
        return

    _restart_cb_server(cb_port, f"CB restarted with {model} ✓")


def _run_restart_cb(reason: str) -> None:
    cb_port = int(os.environ.get("CONTEXT_BRIDGE_PORT", "8755"))
    _restart_cb_server(cb_port, reason)


def _restart_cb_server(cb_port: int, success_message: str) -> None:
    # Step 1 — kill CB
    with _apply_lock:
        _apply_state.update({"status": "restarting", "message": "Stopping CB server…"})
    try:
        result = subprocess.run("netstat -ano", shell=True, capture_output=True, text=True)
        pids: set[str] = set()
        for line in result.stdout.splitlines():
            if f":{cb_port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    pids.add(parts[-1])
        for pid in pids:
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, check=False)
        time.sleep(1)
    except Exception as exc:
        with _apply_lock:
            _apply_state.update({"status": "error", "message": f"Stop failed: {exc}"})
        return

    # Step 2 — restart CB
    with _apply_lock:
        _apply_state.update({"status": "restarting", "message": "Starting CB server…"})
    try:
        flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        subprocess.Popen(
            [PYTHON_EXE, str(CB_SCRIPT)],
            env=os.environ.copy(),
            cwd=str(PROJECT_ROOT / "context_bridge"),
            creationflags=flags,
        )
        time.sleep(2)
        with _apply_lock:
            _apply_state.update({"status": "done", "message": success_message})
    except Exception as exc:
        with _apply_lock:
            _apply_state.update({"status": "error", "message": f"Start failed: {exc}"})


def _backfill_blanks(target: dict, defaults: dict) -> None:
    """Fill any missing or blank (''/None) VALUE field with its known-good default.
    Leaves booleans and explicitly-set values untouched."""
    if not isinstance(target, dict):
        return
    for key, default_value in defaults.items():
        current = target.get(key)
        if key not in target or current is None or (isinstance(current, str) and current.strip() == ""):
            target[key] = default_value

# Singleton summary/snapshot files (fixed names).
RESETTABLE_USAGE_FILES = (
    USAGE_DIR / "dashboard_stats.json",
    USAGE_DIR / "dashboard_stats.js",
    USAGE_DIR / "latest_eval_summary.json",
    USAGE_DIR / "latest_hybrid_eval_summary.json",
    USAGE_DIR / "latest_semantic_hybrid_eval_summary.json",
    USAGE_DIR / "latest_code_location_eval_summary.json",
    USAGE_DIR / "latest_graphify_enrichment_report.json",
    USAGE_DIR / "latest_full_quality_suite.json",
)

# Raw logs are month-partitioned by the MCP runtime (events_2026_06.jsonl,
# outcomes_2026_06.jsonl, tool_calls_2026_06.jsonl). Match them by glob so reset
# actually clears the live files — fixed names like "events.jsonl" never exist.
RESETTABLE_USAGE_GLOBS = (
    (USAGE_DIR, "events*.jsonl"),
    (USAGE_DIR, "outcomes*.jsonl"),
    (USAGE_DIR, "tool_calls*.jsonl"),
    (TEST_USAGE_DIR, "events*.jsonl"),
    (TEST_USAGE_DIR, "outcomes*.jsonl"),
    (TEST_USAGE_DIR, "tool_calls*.jsonl"),
)


def _get_active_mode() -> str:
    config_name = os.environ.get("CONTEXT_BRIDGE_CONFIG", "config.hybrid.json")
    if "semantic" in config_name:
        return "semantic"
    if "hybrid" in config_name:
        return "hybrid"
    return "keyword"


def _get_active_runtime() -> dict:
    config_name = (os.environ.get("CONTEXT_BRIDGE_CONFIG") or "config.hybrid.json").strip() or "config.hybrid.json"
    runtime = {
        "config_name": config_name,
        "server_mode": _get_active_mode(),
        "default_mode": _get_active_mode(),
        "embedding_backend": RAG_DEFAULTS["embedding_backend"],
        "embedding_model": RAG_DEFAULTS["embedding_model"],
        "rag_enabled": _get_active_mode() in ("hybrid", "semantic"),
    }
    config_path = CONFIG_DIR / config_name
    if not config_path.exists():
        return runtime
    try:
        raw = json.loads(config_path.read_text("utf-8"))
    except Exception:
        return runtime

    settings = raw.get("settings") if isinstance(raw.get("settings"), dict) else None
    rag = settings.get("rag") if isinstance(settings, dict) and isinstance(settings.get("rag"), dict) else raw.get("rag")
    if not isinstance(rag, dict):
        return runtime

    default_mode = str(rag.get("default_mode") or runtime["default_mode"]).strip().lower() or runtime["default_mode"]
    embedding_backend = str(rag.get("embedding_backend") or runtime["embedding_backend"]).strip() or runtime["embedding_backend"]
    embedding_model = str(rag.get("embedding_model") or runtime["embedding_model"]).strip() or runtime["embedding_model"]
    runtime.update({
        "default_mode": default_mode,
        "embedding_backend": embedding_backend,
        "embedding_model": embedding_model,
        "rag_enabled": bool(rag.get("enabled", runtime["rag_enabled"])),
    })

    manifest_path: Path | None = None
    if runtime["server_mode"] == "semantic" or default_mode == "semantic":
        manifest_path = CONFIG_DIR / "data" / "vector_meta.semantic.json"
    elif runtime["server_mode"] == "hybrid" or default_mode == "hybrid":
        manifest_path = CONFIG_DIR / "data" / "vector_meta.json"

    if manifest_path and manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
            runtime["embedding_backend"] = str(manifest.get("embedding_backend") or runtime["embedding_backend"]).strip() or runtime["embedding_backend"]
            runtime["embedding_model"] = str(manifest.get("embedding_model") or runtime["embedding_model"]).strip() or runtime["embedding_model"]
            runtime["vector_manifest"] = manifest_path.name
        except Exception:
            pass
    return runtime


def _get_ollama_status() -> dict:
    base = "http://localhost:11434"
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=2) as r:
            tags_data = json.loads(r.read())
        available = [m["name"] for m in tags_data.get("models", [])]
    except Exception:
        return {"running": False, "available_models": [], "loaded_models": []}
    try:
        with urllib.request.urlopen(f"{base}/api/ps", timeout=2) as r:
            ps_data = json.loads(r.read())
        loaded = [m["name"] for m in ps_data.get("models", [])]
    except Exception:
        loaded = []
    return {"running": True, "available_models": available, "loaded_models": loaded}


def _deep_merge(base: dict, updates: dict) -> None:
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def clear_dashboard_usage_data() -> dict[str, list[str]]:
    deleted: list[str] = []
    missing: list[str] = []

    # Collect targets: fixed singletons + glob-matched partitioned logs.
    targets: list[Path] = list(RESETTABLE_USAGE_FILES)
    for directory, pattern in RESETTABLE_USAGE_GLOBS:
        if directory.exists():
            targets.extend(sorted(directory.glob(pattern)))

    for path in targets:
        if path.exists():
            path.unlink()
            deleted.append(str(path.relative_to(PROJECT_ROOT)))
        else:
            missing.append(str(path.relative_to(PROJECT_ROOT)))
    return {
        "deleted_files": deleted,
        "missing_files": missing,
    }


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.path = "/index.html"
            return super().do_GET()
        if path == "/api/apply-model-status":
            return self.send_apply_status()
        if path == "/api/restart-cb-status":
            return self.send_apply_status()
        if path == "/api/stats":
            return self.send_stats()
        if path == "/api/config":
            return self.send_config()
        if path == "/api/prompt-config":
            return self.send_prompt_config()
        if path == "/api/qwen-input":
            return self.send_qwen_input()
        if path == "/api/qwen-output":
            return self.send_qwen_output()
        if path == "/api/gap-search":
            return self.send_gap_search()
        return super().do_GET()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", f"http://127.0.0.1:{PORT}")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/reset-dashboard-data":
            return self.reset_dashboard_data()
        if path == "/api/config":
            return self.save_config()
        if path == "/api/clear-analysis-cache":
            return self.clear_analysis_cache()
        if path == "/api/clear-rules-cache":
            return self.clear_rules_cache()
        if path == "/api/apply-model":
            return self.apply_model()
        if path == "/api/restart-cb":
            return self.restart_cb()
        self.send_error(404, "Not found")

    def _send_json(self, data: dict, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", f"http://127.0.0.1:{PORT}")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass

    def send_qwen_input(self) -> None:
        try:
            log_path = PROJECT_ROOT / "context_bridge" / "usage" / "last_qwen_prompt.json"
            if not log_path.exists():
                self._send_json({"available": False, "message": "No Qwen query logged yet. Run a search first."})
                return
            data = json.loads(log_path.read_text("utf-8"))
            self._send_json({"available": True, **data})
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def send_qwen_output(self) -> None:
        try:
            log_path = PROJECT_ROOT / "context_bridge" / "usage" / "last_qwen_output.json"
            if not log_path.exists():
                self._send_json({"available": False, "message": "No Qwen output logged yet. Run a search first."})
                return
            data = json.loads(log_path.read_text("utf-8"))
            self._send_json({"available": True, **data})
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def send_gap_search(self) -> None:
        try:
            log_path = PROJECT_ROOT / "context_bridge" / "usage" / "last_gap_search.json"
            if not log_path.exists():
                self._send_json({"available": False, "message": "No gap re-search logged yet."})
                return
            data = json.loads(log_path.read_text("utf-8"))
            self._send_json({"available": True, **data})
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def send_prompt_config(self) -> None:
        try:
            import re
            prompt_file = PROJECT_ROOT / "context_bridge" / "analysis" / "prompt.py"
            text = prompt_file.read_text("utf-8")
            def extract(name: str) -> int | None:
                m = re.search(rf"^{name}\s*=\s*([\d_]+)", text, re.MULTILINE)
                return int(m.group(1).replace("_", "")) if m else None
            self._send_json({
                "max_prompt_chars":      extract("_MAX_PROMPT_CHARS"),
                "max_code_block_chars":  extract("_MAX_CODE_BLOCK_CHARS"),
                "max_code_blocks":       extract("_MAX_CODE_BLOCKS"),
                "prompt_file":           "context_bridge/analysis/prompt.py",
            })
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def send_stats(self) -> None:
        global _stats_cache, _stats_cache_fp
        try:
            fp = _stats_fingerprint()
            if _stats_cache is not None and fp == _stats_cache_fp:
                self._send_json(_stats_cache)
                return
            from context_bridge.scripts.build_dashboard_stats import build_stats
            result = build_stats()
            _stats_cache = result
            _stats_cache_fp = fp
            self._send_json(result)
        except ImportError as exc:
            self._send_json({"error": f"Dashboard stats module not available: {exc}"}, status=503)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def send_config(self) -> None:
        configs: dict = {}
        for name, file_path in CONFIG_FILES.items():
            if file_path.exists():
                try:
                    configs[name] = json.loads(file_path.read_text("utf-8"))
                except Exception:
                    configs[name] = None
            else:
                configs[name] = None

        self._send_json({
            "configs": configs,
            "active_mode": _get_active_mode(),
            "active_runtime": _get_active_runtime(),
            "test_mode": os.environ.get("CONTEXT_BRIDGE_TEST_MODE") == "1",
            "port": os.environ.get("CONTEXT_BRIDGE_PORT", "8755"),
            "ollama": _get_ollama_status(),
        })

    def save_config(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            config_name = data.get("config", "")
            updates = data.get("updates", {})

            if config_name not in CONFIG_FILES:
                self.send_error(400, "Invalid config name")
                return

            file_path = CONFIG_FILES[config_name]
            if not file_path.exists():
                self.send_error(404, "Config file not found")
                return

            config = json.loads(file_path.read_text("utf-8"))

            # Preserve existing model/provider before merge — used as fallback if form sends blank
            existing_stage = (config.get("pipeline") or {}).get("analysis_stage") or {}
            existing_model    = existing_stage.get("model", "")
            existing_provider = existing_stage.get("provider", "ollama")

            _deep_merge(config, updates)

            # Resilience: never let a blank/cleared form wipe critical values.
            # Backfill blank VALUE fields with known-good defaults (toggles untouched).
            stage = (config.get("pipeline") or {}).get("analysis_stage")
            if isinstance(stage, dict):
                # model/provider: fall back to what was already in the config, not a hardcoded string
                if not (stage.get("model") or "").strip():
                    stage["model"] = existing_model
                if not (stage.get("provider") or "").strip():
                    stage["provider"] = existing_provider
                _backfill_blanks(stage, ANALYSIS_STAGE_DEFAULTS)
            rag = (config.get("settings") or {}).get("rag")
            if isinstance(rag, dict):
                _backfill_blanks(rag, RAG_DEFAULTS)
                # Mode is a startup decision (which config file the .bat loads).
                # rag.enabled is DERIVED from default_mode — never independently editable.
                # This makes it impossible for a dashboard save to silently flip the
                # server into keyword mode and contradict the mode it was started in.
                mode = str(rag.get("default_mode") or "hybrid").strip().lower()
                rag["enabled"] = mode in ("hybrid", "semantic")

            file_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), "utf-8")
            self._send_json({"ok": True, "message": "Saved successfully."})
        except Exception as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=500)

    def clear_analysis_cache(self) -> None:
        try:
            cleared = 0
            try:
                import diskcache
                cache_dir = PROJECT_ROOT / "context_bridge" / "cache" / "analysis"
                if cache_dir.exists():
                    cache = diskcache.Cache(str(cache_dir))
                    cleared = len(cache)
                    cache.clear()
                    cache.close()
            except ImportError:
                pass
            self._send_json({"ok": True, "message": f"Analysis cache cleared — {cleared} entr{'y' if cleared == 1 else 'ies'} removed."})
        except Exception as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=500)

    def clear_rules_cache(self) -> None:
        try:
            sentinel = USAGE_DIR / "rules_cache_reset.sentinel"
            sentinel.write_text(str(time.time()), "utf-8")
            self._send_json({"ok": True, "message": "Rules cache cleared — next search will reload rules from disk."})
        except Exception as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=500)

    def reset_dashboard_data(self) -> None:
        result = clear_dashboard_usage_data()
        self._send_json({"ok": True, "message": "Dashboard usage data cleared.", **result})

    def send_apply_status(self) -> None:
        with _apply_lock:
            self._send_json(dict(_apply_state))

    def apply_model(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length))
            model  = (body.get("model") or "").strip()
            if not model:
                self._send_json({"ok": False, "message": "No model specified."}, status=400)
                return
            with _apply_lock:
                if _apply_state.get("status") in ("warming_up", "restarting"):
                    self._send_json({"ok": False, "message": "Apply already in progress."}, status=409)
                    return
                _apply_state.update({"status": "starting", "message": "Starting…"})
            threading.Thread(target=_run_apply_model, args=(model,), daemon=True).start()
            self._send_json({"ok": True, "message": "Apply started."})
        except Exception as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=500)

    def restart_cb(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            reason = (body.get("reason") or "CB restarted with updated retrieval settings ✓").strip()
            with _apply_lock:
                if _apply_state.get("status") in ("warming_up", "restarting"):
                    self._send_json({"ok": False, "message": "Apply already in progress."}, status=409)
                    return
                _apply_state.update({"status": "starting", "message": "Starting…"})
            threading.Thread(target=_run_restart_cb, args=(reason,), daemon=True).start()
            self._send_json({"ok": True, "message": "Restart started."})
        except Exception as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=500)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), DashboardHandler)
    print(f"ContextBridge dashboard: http://127.0.0.1:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
