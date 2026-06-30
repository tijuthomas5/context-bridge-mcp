from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_RULES_TTL = 300.0  # 5 minutes
_rules_cache: dict[tuple[str, str, str], tuple[dict[str, Any], float]] = {}

# Sentinel file written by the dashboard "Clear Rules Cache" button.
# When its mtime is newer than the cache entry, the cache is force-invalidated.
_SENTINEL_FILENAME = "rules_cache_reset.sentinel"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _merge_rule_payloads(core: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "profile": str(project.get("profile") or core.get("profile") or "default"),
        "semantic_rules": [],
    }
    merged["semantic_rules"].extend(list(core.get("semantic_rules") or []))
    merged["semantic_rules"].extend(list(project.get("semantic_rules") or []))
    return merged


def _sentinel_mtime(project_root: str) -> float:
    """Return mtime of the rules cache reset sentinel, or 0.0 if it doesn't exist."""
    try:
        return (Path(project_root) / "context_bridge" / "usage" / _SENTINEL_FILENAME).stat().st_mtime
    except OSError:
        return 0.0


def load_ranking_rules(project_root: str, rules_root: str, project_profile: str) -> dict[str, Any]:
    cache_key = (project_root, rules_root, project_profile)
    cached = _rules_cache.get(cache_key)
    if cached is not None:
        result, ts = cached
        sentinel = _sentinel_mtime(project_root)
        cache_wall_time = time.time() - (time.monotonic() - ts)
        if time.monotonic() - ts < _RULES_TTL and sentinel <= cache_wall_time:
            return result
    base_root = Path(project_root)
    root = base_root / rules_root
    core = _read_json(root / "core_rules.json")
    project = _read_json(root / "projects" / f"{project_profile}_rules.json") if project_profile else {}
    result = _merge_rule_payloads(core, project)
    _rules_cache[cache_key] = (result, time.monotonic())
    return result
