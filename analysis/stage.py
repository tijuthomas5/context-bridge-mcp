from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

try:
    import diskcache
    _CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "analysis"
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _ANALYSIS_CACHE = diskcache.Cache(str(_CACHE_DIR))
    _DISK_CACHE = True
except ImportError:
    _ANALYSIS_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
    _DISK_CACHE = False

_CACHE_TTL = 300.0       # seconds — skip re-calling the analysis LLM for identical queries
_MAX_RETRIES = 3
_RETRY_DELAY = 1.0       # seconds between retries
_FALLBACK_BLOCK_COUNT = 3  # blocks returned on parse failure (not all of them)
_BG_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cb-analysis")


def _retrieval_fingerprint(retrieval: dict[str, Any]) -> str:
    # Stable identity from sorted file paths — cheap, captures what was actually retrieved
    paths = sorted(
        str(f.get("path") or "")
        for f in (retrieval.get("files") or [])
        if f.get("path")
    )
    return hashlib.md5("\n".join(paths).encode("utf-8")).hexdigest()


def _cache_key(query: str, provider: str, model: str, retrieval: dict[str, Any]) -> str:
    raw = f"{query}::{provider}::{model}::{_retrieval_fingerprint(retrieval)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict[str, Any] | None:
    if _DISK_CACHE:
        entry = _ANALYSIS_CACHE.get(key)
        return entry if isinstance(entry, dict) else None
    else:
        entry = _ANALYSIS_CACHE.get(key)
        if entry is None:
            return None
        result, ts = entry
        return result if time.monotonic() - ts < _CACHE_TTL else None


def _cache_set(key: str, value: dict[str, Any]) -> None:
    if _DISK_CACHE:
        _ANALYSIS_CACHE.set(key, value, expire=_CACHE_TTL)
    else:
        _ANALYSIS_CACHE[key] = (value, time.monotonic())


def _run_analysis_blocking(
    query: str,
    retrieval: dict[str, Any],
    project_root: Path,
    cache_key: str,
) -> dict[str, Any]:
    from .config import analysis_stage_config, load_runtime_section
    from .prompt import get_system_prompt, build_user_prompt
    from .providers import create_provider

    stage_cfg = analysis_stage_config(project_root)
    provider_name = str(stage_cfg.get("provider") or "ollama")
    model = str(stage_cfg.get("model") or "")

    profile_env = (os.environ.get("CONTEXT_BRIDGE_PROFILE") or "").strip().lower()
    if profile_env:
        project_profile = profile_env
        rules_root = "context_bridge/rules"
    else:
        runtime = load_runtime_section(project_root)
        project_profile = str(runtime.get("project_profile") or "").strip().lower() or "default"
        rules_root = str(runtime.get("rules_root") or "context_bridge/rules").replace("\\", "/").strip("/") or "context_bridge/rules"
    try:
        _src_dir = str(Path(__file__).resolve().parent.parent / "src")
        if _src_dir not in sys.path:
            sys.path.insert(0, _src_dir)
        from cb_profiles import load_profile
        _profile = load_profile(project_root, rules_root, project_profile)
        _prompt_override = _profile.analysis_prompt_override()
        if _prompt_override:
            print(f"[ContextBridge] stage: '{project_profile}' prompt override loaded ({len(_prompt_override)} chars)", file=sys.stderr)
        else:
            print(f"[ContextBridge] stage: '{project_profile}' profile returned no prompt override → using generic prompt", file=sys.stderr)
    except Exception as e:
        print(f"[ContextBridge] stage: profile load failed for '{project_profile}': {e} → using generic prompt", file=sys.stderr)
        _prompt_override = None
    SYSTEM_PROMPT = get_system_prompt(_prompt_override)

    try:
        provider = create_provider(stage_cfg)
    except Exception as exc:
        print(f"[ContextBridge] Analysis stage provider init failed: {exc}", file=sys.stderr)
        return {"enabled": True, "error": str(exc), "skipped": True}

    user_prompt, prompt_chars = build_user_prompt(query, retrieval)

    # Log full Qwen input for dashboard inspection
    try:
        log_path = Path(__file__).resolve().parent.parent / "usage" / "last_qwen_prompt.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "query": query,
            "provider": provider_name,
            "model": model,
            "prompt_chars": prompt_chars,
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt": user_prompt,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    last_exc: Exception | None = None
    t_start = time.monotonic()

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            raw_response = provider.complete(SYSTEM_PROMPT, user_prompt)
            break
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAY * (2 ** (attempt - 1))
                print(
                    f"[ContextBridge] Analysis stage attempt {attempt}/{_MAX_RETRIES} failed ({type(exc).__name__}): {exc}"
                    f" — retrying in {delay:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(delay)
    else:
        print(
            f"[ContextBridge] Analysis stage gave up after {_MAX_RETRIES} attempts ({provider_name}/{model}): {last_exc}",
            file=sys.stderr,
        )
        return {"enabled": True, "error": str(last_exc), "skipped": True}

    provider_latency_ms = int((time.monotonic() - t_start) * 1000)
    analysis = _parse_analysis(raw_response, provider_name, model, prompt_chars, provider_latency_ms)

    if not analysis.get("parse_error") and not analysis.get("skipped"):
        _cache_set(cache_key, analysis)

    # Log Qwen output for dashboard inspection
    try:
        out_path = Path(__file__).resolve().parent.parent / "usage" / "last_qwen_output.json"
        out_path.write_text(json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "query": query,
            "provider": provider_name,
            "model": model,
            "latency_ms": provider_latency_ms,
            "raw_response": raw_response[:8000],
            "parsed": analysis,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return analysis


def run_analysis_stage(
    query: str,
    retrieval: dict[str, Any],
    project_root: Path,
    background: bool = False,
) -> dict[str, Any]:
    from .config import analysis_stage_config, is_analysis_enabled

    if not is_analysis_enabled(project_root):
        return {"enabled": False, "skipped": True}

    stage_cfg = analysis_stage_config(project_root)
    provider_name = str(stage_cfg.get("provider") or "ollama")
    model = str(stage_cfg.get("model") or "")
    key = _cache_key(query, provider_name, model, retrieval)

    cached = _cache_get(key)
    if cached is not None:
        return {**cached, "cache_hit": True}

    if background:
        # Fire Qwen in background — return immediately, result cached when done
        _BG_EXECUTOR.submit(_run_analysis_blocking, query, retrieval, project_root, key)
        return {"enabled": True, "skipped": True, "background": True, "cache_key": key}

    return _run_analysis_blocking(query, retrieval, project_root, key)


def run_reflection_pass(
    query: str,
    retrieval: dict[str, Any],
    first_pass: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    """
    Second local AI call — self-reflection.
    The local AI receives its own first-pass output alongside the original retrieval
    and is asked to verify its findings against the prompt, then correct any gaps.
    Returns a corrected analysis dict, or first_pass unchanged on failure.
    """
    from .config import analysis_stage_config
    from .prompt import get_system_prompt, build_reflection_prompt
    from .providers import create_provider

    stage_cfg = analysis_stage_config(project_root)
    try:
        provider = create_provider(stage_cfg)
    except Exception as exc:
        print(f"[ContextBridge] Reflection pass provider init failed: {exc}", file=sys.stderr)
        return {**first_pass, "skipped": True, "reflection_error": str(exc)}

    try:
        from .prompt import get_system_prompt
        import os
        profile_env = (os.environ.get("CONTEXT_BRIDGE_PROFILE") or "").strip().lower()
        if profile_env:
            rules_root = "context_bridge/rules"
            project_profile = profile_env
        else:
            from .config import load_runtime_section
            runtime = load_runtime_section(project_root)
            project_profile = str(runtime.get("project_profile") or "").strip().lower() or "default"
            rules_root = str(runtime.get("rules_root") or "context_bridge/rules").replace("\\", "/").strip("/") or "context_bridge/rules"

        import sys as _sys
        _src_dir = str(Path(__file__).resolve().parent.parent / "src")
        if _src_dir not in _sys.path:
            _sys.path.insert(0, _src_dir)
        from cb_profiles import load_profile
        _profile = load_profile(project_root, rules_root, project_profile)
        _prompt_override = _profile.analysis_prompt_override()
        SYSTEM_PROMPT = get_system_prompt(_prompt_override)
    except Exception:
        SYSTEM_PROMPT = get_system_prompt(None)

    try:
        user_prompt, _ = build_reflection_prompt(query, retrieval, first_pass)
        raw_response = provider.complete(SYSTEM_PROMPT, user_prompt)
        result = _parse_analysis(raw_response, "reflection", str(stage_cfg.get("model") or ""), 0, 0)
        if result.get("parse_error") or result.get("skipped"):
            return {**first_pass, "skipped": True, "reflection_error": "parse_failed"}
        result["reflection"] = True
        return result
    except Exception as exc:
        print(f"[ContextBridge] Reflection pass failed: {exc}", file=sys.stderr)
        return {**first_pass, "skipped": True, "reflection_error": str(exc)}


def _parse_analysis(
    raw: str,
    provider: str,
    model: str,
    prompt_chars: int,
    provider_latency_ms: int,
) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(l for l in lines if not l.startswith("```")).strip()

    metrics = {
        "provider_latency_ms": provider_latency_ms,
        "prompt_chars": prompt_chars,
    }

    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("top-level must be object")
        selected_ids = list(parsed.get("selected_code_block_ids") or [])
        missing_required_fields = [
            field
            for field in ("relevance_check", "confidence", "summary", "ranked_files")
            if field not in parsed or parsed.get(field) in (None, "", [])
        ]
        return {
            "enabled": True,
            "provider": provider,
            "model": model,
            "parse_error": False,
            "cache_hit": False,
            "relevance_check": str(parsed.get("relevance_check") or ""),
            "confidence": str(parsed.get("confidence") or ""),
            "topics": list(parsed.get("topics") or []),
            "ignored_files": list(parsed.get("ignored_files") or []),
            "gap_search_queries": list(parsed.get("gap_search_queries") or []),
            "summary": str(parsed.get("summary") or ""),
            "current_implementation": str(parsed.get("current_implementation") or ""),
            "workflow": str(parsed.get("workflow") or ""),
            "ranked_files": list(parsed.get("ranked_files") or []),
            "selected_symbols": list(parsed.get("selected_symbols") or []),
            "selected_code_block_ids": selected_ids,
            "dependencies": list(parsed.get("dependencies") or []),
            "impacted_files": list(parsed.get("impacted_files") or []),
            "risks": list(parsed.get("risks") or []),
            "parse_incomplete": bool(missing_required_fields),
            "missing_required_fields": missing_required_fields,
            **metrics,
            "selected_block_count": len(selected_ids),
        }
    except (json.JSONDecodeError, ValueError):
        print(f"[ContextBridge] Analysis stage parse failed for {provider}/{model}", file=sys.stderr)
        return {
            "enabled": True,
            "provider": provider,
            "model": model,
            "parse_error": True,
            "cache_hit": False,
            "raw": raw[:4000],
            **metrics,
            "selected_block_count": 0,
        }


def select_code_blocks_for_analysis(
    analysis: dict[str, Any],
    retrieval: dict[str, Any],
) -> list[dict[str, Any]]:
    all_blocks: list[dict[str, Any]] = list(retrieval.get("code_blocks") or [])

    if analysis.get("skipped") or not analysis.get("enabled"):
        return all_blocks[:_FALLBACK_BLOCK_COUNT]

    if analysis.get("parse_error"):
        # Don't explode token usage — top-N only
        return all_blocks[:_FALLBACK_BLOCK_COUNT]

    selected_ids: set[str] = set(analysis.get("selected_code_block_ids") or [])
    if not selected_ids:
        return all_blocks[:_FALLBACK_BLOCK_COUNT]

    matched = [
        b for b in all_blocks
        if (b.get("block_id") or b.get("id") or "") in selected_ids
    ]
    return matched if matched else all_blocks[:_FALLBACK_BLOCK_COUNT]
