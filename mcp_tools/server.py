from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from graphify_loader import load_config
from mcp_tools.tools import call_tool


mcp = FastMCP(
    name="context-bridge",
    instructions=(
        "Use ContextBridge before broad repository scans. It searches local "
        "Graphify-derived context and returns likely modules, packs, files, "
        "facts, and provenance."
    ),
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _code_locations_enabled() -> bool:
    config = load_config(_project_root())
    return bool(config.get("enable_code_locations", True))


@mcp.tool()
def health_check() -> dict[str, Any]:
    """Check whether the ContextBridge index exists and is ready."""
    return call_tool("health_check", {})


@mcp.tool()
def search_context(query: str, max_results: int = 8) -> dict[str, Any]:
    """Search Graphify and curated assistant context for relevant files and facts."""
    return call_tool("search_context", {"query": query, "max_results": max_results})


@mcp.tool()
def find_related_files(query: str, max_results: int = 20) -> dict[str, Any]:
    """Return a compact list of likely relevant source files for a query."""
    return call_tool("find_related_files", {"query": query, "max_results": max_results})


if _code_locations_enabled():
    @mcp.tool()
    def find_code_locations(query: str, max_results: int = 8) -> dict[str, Any]:
        """Return likely owner files, symbols, line hints, and dependency links."""
        return call_tool("find_code_locations", {"query": query, "max_results": max_results})


@mcp.tool()
def get_module_summary(module: str, pack: str | None = None, max_results: int = 12) -> dict[str, Any]:
    """Return summary, source files, facts, and sources for a module or pack."""
    return call_tool("get_module_summary", {"module": module, "pack": pack, "max_results": max_results})


@mcp.tool()
def get_graphify_pack(pack_name: str, module: str | None = None, max_results: int = 20) -> dict[str, Any]:
    """Return summary, source manifest, facts, and provenance for a known Graphify pack."""
    return call_tool("get_graphify_pack", {"pack_name": pack_name, "module": module, "max_results": max_results})


@mcp.tool()
def record_outcome(
    event_id: str,
    outcome: str,
    used_suggested_files: int = 0,
    extra_files_read: int = 0,
    needed_extra_search: bool = False,
    missed_files: list[str] | None = None,
    failure_reason: str = "none",
    notes: str = "",
) -> dict[str, Any]:
    """Record whether a ContextBridge result helped or missed important context."""
    return call_tool("record_outcome", {
        "event_id": event_id,
        "outcome": outcome,
        "used_suggested_files": used_suggested_files,
        "extra_files_read": extra_files_read,
        "needed_extra_search": needed_extra_search,
        "missed_files": missed_files or [],
        "failure_reason": failure_reason,
        "notes": notes,
    })


@mcp.tool()
def get_usage_summary() -> dict[str, Any]:
    """Return dashboard-style usage and quality statistics from ContextBridge logs."""
    return call_tool("get_usage_summary", {})


def run_server() -> None:
    mcp.run(transport="stdio")
