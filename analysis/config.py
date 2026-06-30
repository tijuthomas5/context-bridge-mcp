from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

_PIPELINE_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_PIPELINE_CACHE_TTL = 60.0  # re-read config at most once per minute


def load_pipeline_config(project_root: Path) -> dict[str, Any]:
    """Read the top-level 'pipeline' section from the active config file."""
    import json

    # Use the same default as the rest of the system (hybrid, not keyword)
    config_name = (os.environ.get("CONTEXT_BRIDGE_CONFIG") or "config.hybrid.json").strip() or "config.hybrid.json"
    cache_key = config_name
    cached = _PIPELINE_CACHE.get(cache_key)
    if cached is not None:
        result, ts = cached
        if time.monotonic() - ts < _PIPELINE_CACHE_TTL:
            return result

    config_path = project_root / "context_bridge" / config_name
    if not config_path.exists():
        return {}
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    result = dict(raw.get("pipeline") or {})
    _PIPELINE_CACHE[cache_key] = (result, time.monotonic())
    return result


def analysis_stage_config(project_root: Path) -> dict[str, Any]:
    return dict(load_pipeline_config(project_root).get("analysis_stage") or {})


def is_analysis_enabled(project_root: Path) -> bool:
    cfg = analysis_stage_config(project_root)
    return bool(cfg.get("enabled", False))


def is_auto_analyze_enabled(project_root: Path) -> bool:
    cfg = analysis_stage_config(project_root)
    return bool(cfg.get("enabled", False)) and bool(cfg.get("auto_analyze", False))


def auto_analyze_timeout_seconds(project_root: Path) -> int:
    cfg = analysis_stage_config(project_root)
    try:
        return max(10, int(cfg.get("auto_analyze_timeout_seconds", 60)))
    except (TypeError, ValueError):
        return 60


VALID_PIPELINE_MODES = {"simple", "validated", "iterative", "full"}


def pipeline_mode(project_root: Path) -> str:
    """
    simple    — CB only, no local AI
    validated — CB + local AI once (default)
    iterative — CB + local AI + CB gap fill
    full      — CB pre-validate + local AI + gap fill + local AI self-reflect
    """
    cfg = analysis_stage_config(project_root)
    mode = str(cfg.get("pipeline_mode") or "validated").strip().lower()
    return mode if mode in VALID_PIPELINE_MODES else "validated"


def cb_pre_validate_enabled(project_root: Path) -> bool:
    return pipeline_mode(project_root) == "full"


def self_reflection_enabled(project_root: Path) -> bool:
    return pipeline_mode(project_root) == "full"


def gap_fill_enabled(project_root: Path) -> bool:
    return pipeline_mode(project_root) in ("iterative", "full")


def max_gap_iterations(project_root: Path) -> int:
    mode = pipeline_mode(project_root)
    if mode not in ("iterative", "full"):
        return 0
    cfg = analysis_stage_config(project_root)
    try:
        return max(1, min(3, int(cfg.get("max_gap_iterations", 2))))
    except (TypeError, ValueError):
        return 2


def show_ai_meta(project_root: Path) -> bool:
    """When True, CB surfaces model/provider/latency at the top level of every response."""
    cfg = analysis_stage_config(project_root)
    return bool(cfg.get("show_ai_meta", True))  # default ON


def load_runtime_section(project_root: Path) -> dict[str, Any]:
    """Read settings.runtime from the active config file (same config used by the rest of the pipeline)."""
    import json
    config_name = (os.environ.get("CONTEXT_BRIDGE_CONFIG") or "config.hybrid.json").strip() or "config.hybrid.json"
    config_path = project_root / "context_bridge" / config_name
    if not config_path.exists():
        return {}
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict((raw.get("settings") or {}).get("runtime") or {})
