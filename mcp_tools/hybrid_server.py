from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from graphify_loader import load_config
from mcp_tools.hybrid_tools import call_hybrid_tool
from mcp_tools.pipeline_tool import analyze_context as _analyze_context
from mcp_tools.tools import call_tool
from mcp_tools.usage import timed_call


mcp = FastMCP(
    name="context-bridge-hybrid",
    instructions=(
        "Use ContextBridge before broad repository scans. This hybrid server keeps "
        "Graphify keyword owner results first and exposes an opt-in guarded RAG "
        "tool for additional scoped context."
    ),
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _code_locations_enabled() -> bool:
    try:
        config = load_config(_project_root())
        return bool(config.get("enable_code_locations", True))
    except Exception:
        return True  # default on — startup validation will catch missing config separately


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
        return call_hybrid_tool("find_code_locations", {"query": query, "max_results": max_results})


@mcp.tool()
def search_context_hybrid(
    query: str,
    max_results: int | None = None,
    max_files: int | None = None,
    top_k_vector: int | None = None,
    protected_keyword_count: int | None = None,
) -> dict[str, Any]:
    """Search the codebase for relevant files, symbols, and facts. Works for all server modes (hybrid, semantic, keyword) — the active mode is set at server startup, not by the caller. Call this once per task with a focused query. Omitted limits use config defaults."""
    return call_hybrid_tool(
        "search_context_hybrid",
        {
            "query": query,
            "max_results": max_results,
            "max_files": max_files,
            "top_k_vector": top_k_vector,
            "protected_keyword_count": protected_keyword_count,
        },
    )


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
    return call_tool(
        "record_outcome",
        {
            "event_id": event_id,
            "outcome": outcome,
            "used_suggested_files": used_suggested_files,
            "extra_files_read": extra_files_read,
            "needed_extra_search": needed_extra_search,
            "missed_files": missed_files or [],
            "failure_reason": failure_reason,
            "notes": notes,
        },
    )


@mcp.tool()
def analyze_context(
    query: str,
    event_id: str,
) -> dict[str, Any]:
    """
    DEBUG/INTERNAL — analysis runs automatically inside search_context_hybrid() when auto_analyze=true.
    Use this only to manually re-run or debug the analysis stage for a specific event_id.

    Returns:
      ranked_files             ordered files with role, symbols, and reason
      selected_symbols         specific methods/classes flagged by analysis
      dependencies             from→to dependency edges relevant to the task
      risks                    identified risks with severity and owning file
      recommended_code_blocks  minimal code blocks selected for the coding model
    """
    args = {"query": query, "event_id": event_id}
    return timed_call("analyze_context", {"query": query}, lambda: _analyze_context(**args))


@mcp.tool()
def get_usage_summary() -> dict[str, Any]:
    """Return dashboard-style usage and quality statistics from ContextBridge logs."""
    return call_tool("get_usage_summary", {})


def run_server() -> None:
    import os

    transport = os.environ.get("CONTEXT_BRIDGE_TRANSPORT", "stdio").strip().lower()
    if transport == "sse":
        import uvicorn
        from starlette.applications import Starlette

        port_str = os.environ.get("CONTEXT_BRIDGE_PORT", "").strip()
        if not port_str:
            raise RuntimeError("CONTEXT_BRIDGE_PORT is not set. Start the server via start_Context_Bridge.bat.")
        try:
            port = int(port_str)
        except ValueError:
            raise RuntimeError(f"CONTEXT_BRIDGE_PORT='{port_str}' is not a valid port number.")
        # Merge routes from both transport apps into one Starlette app.
        # Paths stay intact (no Mount prefix-stripping), lifespan runs once for all routes.
        # /sse, /messages → SSE clients (Claude Code, Codex)
        # /mcp            → Streamable HTTP clients (Antigravity)
        from contextlib import asynccontextmanager

        _sse_app = mcp.sse_app()
        _streamable_app = mcp.streamable_http_app()

        @asynccontextmanager
        async def _lifespan(app):
            # Silence benign Windows ProactorEventLoop noise: when an SSE/HTTP
            # client disconnects abruptly, asyncio calls socket.shutdown() on an
            # already-reset socket and logs a ConnectionResetError (WinError 10054)
            # from _call_connection_lost. It is harmless — the server keeps running.
            import asyncio

            def _ignore_conn_reset(loop, context):
                exc = context.get("exception")
                if isinstance(exc, ConnectionResetError):
                    return  # client went away mid-stream — nothing to do
                loop.default_exception_handler(context)

            asyncio.get_running_loop().set_exception_handler(_ignore_conn_reset)

            # Run the streamable HTTP app's lifespan so its session manager
            # task group is initialized before any /mcp requests arrive.
            async with _streamable_app.router.lifespan_context(_streamable_app):
                yield

        app = Starlette(
            routes=[*_streamable_app.routes, *_sse_app.routes],
            lifespan=_lifespan,
        )
        uvicorn.run(app, host="127.0.0.1", port=port)
    else:
        mcp.run(transport="stdio")
