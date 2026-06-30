"""
Project ranking-profile loader.

Core ContextBridge keeps no application-specific routing. Per-project keyword
owner-routing lives in a swappable plugin at:

    <rules_root>/projects/<project_profile>_profile.py

A profile module must expose two callables:
    pinned_owner_files(query_tokens: list[str]) -> list[str]
    adjust_owner_score(score, normalized, query_tokens, result, top_specific_packs) -> float

When project_profile is empty / "default" / missing, a no-op profile is used and
ranking falls back to ContextBridge's generic, domain-agnostic scoring — which is
what any new application gets out of the box.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


class NoOpProfile:
    """Domain-agnostic default: contributes no pins and no score adjustment."""

    profile_name = "default"

    def pinned_owner_files(self, query_tokens: list[str]) -> list[str]:
        return []

    def adjust_owner_score(
        self,
        score: float,
        normalized: str,
        query_tokens: list[str],
        result: dict[str, Any] | None = None,
        top_specific_packs: set[str] | None = None,
    ) -> float:
        return score

    def adjust_document_score(
        self,
        score: float,
        query_tokens: list[str],
        doc_path: str,
        doc_pack: str | None,
        doc_title: str,
        doc_text: str,
    ) -> tuple[float, list[str]]:
        return score, []

    def expand_query_tokens(self, query: str, tokens: list[str]) -> list[str]:
        return []

    def adjust_primary_owner_score(self, score: float, normalized: str, query_distinctive: set) -> float:
        return score

    def adjust_scoped_score(
        self,
        score: float,
        normalized: str,
        scoped_modules: set[str],
        scoped_packs: set[str],
    ) -> float:
        """Stage-2 scoping boost: once broad docs identify the dominant module/pack,
        prefer files under that source area. Generic apps return score unchanged;
        profiles apply project-specific module/pack multipliers."""
        return score

    def gap_queries(self) -> list[tuple[tuple[str, ...], str]]:
        """Domain gap-query table: (trigger_words, cb_query).
        Empty for generic apps; profiles may return domain-specific entries."""
        return []

    def analysis_prompt_override(self) -> str | None:
        """Return a full SYSTEM_PROMPT override for the analysis LLM, or None to use the generic prompt."""
        return None

    def module_intent_tokens(self) -> dict[str, set[str]]:
        """Map of module-name → vocab tokens for module-intent detection.
        Generic apps return {} — no module routing; profiles supply domain-specific entries."""
        return {}

    def extra_owner_file_patterns(self) -> tuple[str, ...]:
        """Additional filename patterns (substrings) that identify high-priority owner files.
        Generic apps return () — profiles add project-specific file naming conventions."""
        return ()

    def pack_files_for_intents(self, query_tokens: list[str], graphify_root: str) -> list[str]:
        """Return file paths from Graphify pack source-files.txt for matched intents.
        Generic apps return [] — profiles map intents to their Graphify packs."""
        return []

    def infer_module_from_path(self, path: str) -> str | None:
        """Map a file path to a module name for hybrid fusion scoping.
        Generic apps return None — profiles encode their folder→module conventions."""
        return None

    def low_signal_terms(self) -> tuple[str, ...]:
        """Project-specific low-signal query terms (e.g. module names) that vector
        scoping should treat as non-distinctive. Generic apps return ()."""
        return ()

    def noise_files(self) -> dict[str, list[str]]:
        """Project-specific 'noise' filenames the vector layer should de-prioritize,
        keyed by bucket: 'ui_shell', 'frontend_support', 'backend_root'.
        Generic apps return {} — no penalties."""
        return {}


_NOOP = NoOpProfile()


class _ModuleProfileAdapter:
    """Wraps a profile module so optional hooks fall back to no-op behavior."""

    def __init__(self, module: Any):
        self._m = module
        self.profile_name = getattr(module, "profile_name", getattr(module, "__name__", "profile"))

    def pinned_owner_files(self, query_tokens: list[str]) -> list[str]:
        fn = getattr(self._m, "pinned_owner_files", None)
        return fn(query_tokens) if fn else _NOOP.pinned_owner_files(query_tokens)

    def adjust_owner_score(self, score, normalized, query_tokens, result=None, top_specific_packs=None):
        fn = getattr(self._m, "adjust_owner_score", None)
        if not fn:
            return score
        return fn(score, normalized, query_tokens, result, top_specific_packs)

    def adjust_document_score(self, score, query_tokens, doc_path, doc_pack, doc_title, doc_text):
        fn = getattr(self._m, "adjust_document_score", None)
        if not fn:
            return score, []
        return fn(score, query_tokens, doc_path, doc_pack, doc_title, doc_text)

    def expand_query_tokens(self, query, tokens):
        fn = getattr(self._m, "expand_query_tokens", None)
        return fn(query, tokens) if fn else []

    def adjust_primary_owner_score(self, score, normalized, query_distinctive):
        fn = getattr(self._m, "adjust_primary_owner_score", None)
        return fn(score, normalized, query_distinctive) if fn else score

    def adjust_scoped_score(self, score, normalized, scoped_modules, scoped_packs):
        fn = getattr(self._m, "adjust_scoped_score", None)
        return fn(score, normalized, scoped_modules, scoped_packs) if fn else score

    def gap_queries(self) -> list[tuple[tuple[str, ...], str]]:
        fn = getattr(self._m, "gap_queries", None)
        return fn() if fn else []

    def analysis_prompt_override(self) -> str | None:
        fn = getattr(self._m, "analysis_prompt_override", None)
        return fn() if fn else None

    def module_intent_tokens(self) -> dict[str, set[str]]:
        fn = getattr(self._m, "module_intent_tokens", None)
        return fn() if fn else {}

    def extra_owner_file_patterns(self) -> tuple[str, ...]:
        fn = getattr(self._m, "extra_owner_file_patterns", None)
        return fn() if fn else ()

    def pack_files_for_intents(self, query_tokens: list[str], graphify_root: str) -> list[str]:
        fn = getattr(self._m, "pack_files_for_intents", None)
        return fn(query_tokens, graphify_root) if fn else []

    def infer_module_from_path(self, path: str) -> str | None:
        fn = getattr(self._m, "infer_module_from_path", None)
        return fn(path) if fn else None

    def low_signal_terms(self) -> tuple[str, ...]:
        fn = getattr(self._m, "low_signal_terms", None)
        return fn() if fn else ()

    def noise_files(self) -> dict[str, list[str]]:
        fn = getattr(self._m, "noise_files", None)
        return fn() if fn else {}


def load_profile(project_root: Any, rules_root: str, project_profile: str):
    """Return the profile plugin module for project_profile, or a no-op profile.

    Failure to locate or import a profile is non-fatal — ContextBridge degrades to
    generic ranking rather than crashing the search path.
    """
    name = (project_profile or "").strip().lower()
    if not name or name in ("default", "core", "none"):
        return _NOOP

    path = Path(project_root) / rules_root.replace("\\", "/") / "projects" / f"{name}_profile.py"
    if not path.exists():
        return _NOOP

    try:
        spec = importlib.util.spec_from_file_location(f"cb_profile_{name}", path)
        if spec is None or spec.loader is None:
            return _NOOP
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        return _NOOP

    if not any(hasattr(module, hook) for hook in ("pinned_owner_files", "adjust_owner_score", "adjust_document_score")):
        return _NOOP
    return _ModuleProfileAdapter(module)
