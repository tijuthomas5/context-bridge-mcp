from __future__ import annotations

from typing import Any

from mcp_tools.tools import _project_root


def analyze_context(
    query: str,
    event_id: str,
) -> dict[str, Any]:
    """
    Analysis stage: call search_context_hybrid() first to get an event_id,
    then pass that event_id here. The server looks up the full retrieval from
    its cache and sends it to the configured analysis model (e.g. Qwen).

    Claude never needs to handle the raw retrieval — only the event_id.

    Returns:
      ranked_files         — ordered list of files with role, symbols, reason
      selected_symbols     — specific methods/classes the analysis flagged
      dependencies         — from→to dependency edges relevant to the task
      risks                — identified risks with severity and owning file
      recommended_code_blocks — minimal code blocks selected for the coding model
    """
    from context_bridge.analysis.stage import run_analysis_stage, select_code_blocks_for_analysis
    from mcp_tools.hybrid_tools import get_full_retrieval

    retrieval = get_full_retrieval(event_id)
    if retrieval is None:
        return {
            "error": f"No cached retrieval found for event_id '{event_id}'. "
                     "The cache TTL is 10 minutes — call search_context_hybrid() again.",
            "event_id": event_id,
        }

    project_root = _project_root()
    analysis = run_analysis_stage(query, retrieval, project_root)
    recommended_blocks = select_code_blocks_for_analysis(analysis, retrieval)

    total_retrieval_blocks = len(retrieval.get("code_blocks") or [])

    if analysis.get("skipped"):
        return {
            "query": query,
            "analysis_enabled": False,
            "ranked_files": retrieval.get("files", []),
            "selected_symbols": retrieval.get("symbol_hits", []),
            "dependencies": retrieval.get("dependency_chain", []),
            "risks": [],
            "recommended_code_blocks": recommended_blocks,
            "metrics": {
                "provider_latency_ms": 0,
                "prompt_chars": 0,
                "selected_block_count": len(recommended_blocks),
                "total_retrieval_blocks": total_retrieval_blocks,
                "cache_hit": False,
                "parse_failed": False,
            },
        }

    metrics = {
        "provider_latency_ms": analysis.get("provider_latency_ms", 0),
        "prompt_chars": analysis.get("prompt_chars", 0),
        "selected_block_count": len(recommended_blocks),
        "total_retrieval_blocks": total_retrieval_blocks,
        "cache_hit": bool(analysis.get("cache_hit")),
        "parse_failed": bool(analysis.get("parse_error")),
    }

    return {
        "query": query,
        "analysis_enabled": True,
        "provider": analysis.get("provider"),
        "model": analysis.get("model"),
        "summary": analysis.get("summary", ""),
        "current_implementation": analysis.get("current_implementation", ""),
        "workflow": analysis.get("workflow", ""),
        "ranked_files": analysis.get("ranked_files", []),
        "selected_symbols": analysis.get("selected_symbols", []),
        "dependencies": analysis.get("dependencies", []),
        "impacted_files": analysis.get("impacted_files", []),
        "risks": analysis.get("risks", []),
        "recommended_code_blocks": recommended_blocks,
        "metrics": metrics,
        **({"parse_error": True, "raw": analysis.get("raw")} if analysis.get("parse_error") else {}),
    }
