"""
ContextBridge project profile — EXAMPLE TEMPLATE.

Copy this file to  rules/projects/<your_project>_profile.py  and set
CONTEXT_BRIDGE_PROFILE=<your_project>  (in your start script) to activate it.

A profile injects YOUR application's domain knowledge into ContextBridge's
generic ranking engine. EVERY hook is OPTIONAL — delete the ones you don't need
and the engine falls back to generic, domain-agnostic behavior for that hook.

The engine calls these hooks at each stage of retrieval/ranking. Nothing here is
required for ContextBridge to work; profiles only *improve* ranking for a project.

The examples below use a fictional e-commerce app with modules:
  orders, catalog, users.  Replace everything with your own names/paths.
"""
from __future__ import annotations

# Optional: a label shown in diagnostics.
profile_name = "example"


# ─── Query expansion ──────────────────────────────────────────────────────
def expand_query_tokens(query: str, tokens: list[str]) -> list[str]:
    """Return EXTRA search tokens to add for a query. Use to map user words to
    the identifiers/files in your codebase. Return [] to add nothing."""
    out: list[str] = []
    token_set = set(tokens)
    if {"checkout", "cart"}.intersection(token_set):
        out.extend(["ordersservice", "cartcontroller", "checkout"])
    return out


# ─── Module vocabulary ────────────────────────────────────────────────────
def module_intent_tokens() -> dict[str, set[str]]:
    """Map each module name to the vocabulary that signals it. Used both for
    module-intent detection and to treat module names as non-distinctive."""
    return {
        "orders": {"order", "orders", "checkout", "cart", "payment"},
        "catalog": {"product", "products", "catalog", "inventory", "sku"},
        "users": {"user", "users", "account", "login", "auth", "permission"},
    }


# ─── Pinned owner files ───────────────────────────────────────────────────
def pinned_owner_files(query_tokens: list[str]) -> list[str]:
    """Force specific files to the TOP of results when the query matches an
    intent. Return workspace-relative paths. Return [] to pin nothing."""
    tokens = set(query_tokens)
    if {"checkout", "payment"}.intersection(tokens):
        return [
            "your_backend/Services/OrdersService.cs",
            "your_backend/Controllers/CheckoutController.cs",
        ]
    return []


# ─── Score adjustments ────────────────────────────────────────────────────
def adjust_document_score(
    score: float,
    query_tokens: list[str],
    doc_path: str,
    doc_pack: str | None,
    doc_title: str,
    doc_text: str,
) -> tuple[float, list[str]]:
    """Boost/penalize a candidate document. Return (new_score, reasons)."""
    reasons: list[str] = []
    if "checkout" in query_tokens and "orders" in doc_path.lower():
        score *= 1.3
        reasons.append("boosted orders module for checkout query")
    return score, reasons


def adjust_owner_score(
    score: float,
    normalized: str,
    query_tokens: list[str],
    result: dict | None = None,
    top_specific_packs: set | None = None,
) -> float:
    """Boost/penalize an owner-file candidate by exact filename/path."""
    if "payment" in query_tokens and normalized.endswith("paymentservice.cs"):
        score += 500.0
    return score


def adjust_primary_owner_score(score: float, normalized: str, query_distinctive: set) -> float:
    """Final nudge for the single primary owner file."""
    return score


def adjust_scoped_score(score: float, normalized: str, scoped_modules: set, scoped_packs: set) -> float:
    """Once the result set settles on a dominant module/pack, prefer files under
    that area. Multipliers are project tuning — adjust to taste."""
    if "orders" in scoped_modules and "/orders/" in normalized:
        score *= 1.2
    return score


# ─── File / module conventions ────────────────────────────────────────────
def extra_owner_file_patterns() -> tuple[str, ...]:
    """Extra filename substrings that mark high-priority owner files."""
    return ("api.ts", "types.ts")


def infer_module_from_path(path: str) -> str | None:
    """Map a file path to a module name (for hybrid fusion scoping)."""
    p = path.replace("\\", "/").lower()
    if "/orders/" in p:
        return "orders"
    if "/catalog/" in p:
        return "catalog"
    if "/users/" in p:
        return "users"
    return None


def low_signal_terms() -> tuple[str, ...]:
    """Project module/domain words the vector layer should treat as low-signal."""
    return ("orders", "catalog", "users")


def noise_files() -> dict:
    """Filenames the vector layer should de-prioritize, by bucket."""
    return {
        "ui_shell": ["app.tsx", "layout.tsx", "router.tsx"],
        "frontend_support": ["client.ts", "api.ts", "store.ts"],
        "backend_root": ["program.cs", "startup.cs"],
    }


# ─── Gap re-search ────────────────────────────────────────────────────────
def gap_queries() -> list[tuple[tuple[str, ...], str]]:
    """When the local AI flags a missing topic, map trigger words in the user's
    issue text to a clean CB re-search query. (trigger_words, query)."""
    return [
        (("checkout", "payment", "cart"), "orders checkout payment service"),
        (("login", "auth", "permission"), "users auth permission login"),
    ]


# ─── Local-AI prompt override ─────────────────────────────────────────────
def analysis_prompt_override() -> str | None:
    """Return a full SYSTEM_PROMPT for the analysis LLM tuned to your domain,
    or None to use ContextBridge's built-in generic prompt."""
    return None


# ─── Graphify pack mapping (advanced) ─────────────────────────────────────
def pack_files_for_intents(query_tokens: list[str], graphify_root: str) -> list[str]:
    """Return file paths from your Graphify packs' source-files.txt for matched
    intents. Return [] to skip. (Advanced — most profiles can omit this.)"""
    return []
