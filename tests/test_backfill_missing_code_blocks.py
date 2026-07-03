"""
Unit tests for backfill_missing_code_blocks() in mcp_tools/hybrid_tools.py.

Covers the bug found in review: a pin/pack-promoted file can become files[0]
after the post-fusion pin reorder, while `code_blocks` still only reflects the
pre-fusion keyword search and has no entry for that file. backfill_missing_code_blocks()
closes that gap by reusing enrich_symbol_hits() for exactly the files that need it,
without exceeding the configured code_block_max_blocks budget.

Run directly: python context_bridge/tests/test_backfill_missing_code_blocks.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_CONTEXT_BRIDGE_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _CONTEXT_BRIDGE_ROOT.parent
for _p in (str(_PROJECT_ROOT), str(_CONTEXT_BRIDGE_ROOT), str(_CONTEXT_BRIDGE_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mcp_tools.hybrid_tools import backfill_missing_code_blocks  # noqa: E402


def fake_enrich_fn(project_root, config, symbol_hits, file_cache):
    """Stub mirroring enrich_symbol_hits()'s contract: returns
    (enriched_symbol_hits_with_code_block_field, list_of_code_blocks)."""
    enriched = []
    blocks = []
    for hit in symbol_hits:
        block = {"path": hit["path"], "symbol": hit["label"], "text": f"fake block for {hit['label']}"}
        new_hit = dict(hit)
        new_hit["code_block"] = block
        enriched.append(new_hit)
        blocks.append(block)
    return enriched, blocks


def test_pin_promoted_file_gets_code_block():
    """Core bug scenario: a pin-promoted file has a symbol hit (injected) but no
    code_block, because code_blocks predates the pin promotion."""
    symbol_hits = [
        {"label": "ExistingMethod", "path": "main_service/Existing.cs", "code_block": {"path": "x", "symbol": "y", "text": "z"}},
        {"label": "PromotedMethod", "path": "main_service/Promoted.cs"},  # no code_block yet
    ]
    code_blocks = [{"path": "main_service/Existing.cs", "symbol": "ExistingMethod", "text": "already here"}]
    injected_paths = {"main_service/promoted.cs"}
    config = {"code_block_max_blocks": 6}

    new_hits, new_blocks = backfill_missing_code_blocks(
        symbol_hits, code_blocks, injected_paths, None, config, fake_enrich_fn
    )
    assert len(new_blocks) == 2, f"expected 2 code_blocks, got {len(new_blocks)}"
    assert any(b["path"] == "main_service/Promoted.cs" for b in new_blocks), "promoted file's code_block missing"
    promoted_hit = next(h for h in new_hits if h["label"] == "PromotedMethod")
    assert "code_block" in promoted_hit, "promoted symbol hit was not enriched with code_block"


def test_no_injected_paths_is_noop():
    symbol_hits = [{"label": "A", "path": "x.cs"}]
    code_blocks = []
    new_hits, new_blocks = backfill_missing_code_blocks(
        symbol_hits, code_blocks, set(), None, {"code_block_max_blocks": 6}, fake_enrich_fn
    )
    assert new_hits is symbol_hits and new_blocks is code_blocks


def test_respects_remaining_budget():
    """Budget already full (6/6) -- must not exceed code_block_max_blocks."""
    code_blocks = [{"path": f"f{i}.cs", "symbol": "m", "text": "t"} for i in range(6)]
    symbol_hits = [{"label": "Promoted", "path": "new.cs"}]
    new_hits, new_blocks = backfill_missing_code_blocks(
        symbol_hits, code_blocks, {"new.cs"}, None, {"code_block_max_blocks": 6}, fake_enrich_fn
    )
    assert len(new_blocks) == 6, f"expected budget to stay at 6, got {len(new_blocks)}"


def test_already_has_code_block_is_skipped():
    """If the promoted file already has a code_block (e.g. from a prior pass),
    do not call enrich_fn again for it."""
    calls = []

    def counting_enrich_fn(project_root, config, symbol_hits, file_cache):
        calls.append(symbol_hits)
        return fake_enrich_fn(project_root, config, symbol_hits, file_cache)

    symbol_hits = [{"label": "A", "path": "already.cs", "code_block": {"path": "already.cs", "symbol": "A", "text": "t"}}]
    code_blocks = [{"path": "already.cs", "symbol": "A", "text": "t"}]
    new_hits, new_blocks = backfill_missing_code_blocks(
        symbol_hits, code_blocks, {"already.cs"}, None, {"code_block_max_blocks": 6}, counting_enrich_fn
    )
    assert calls == [], "enrich_fn should not be called when nothing needs enrichment"


# ---- priority_paths eviction: fixes the review finding that a full budget ----
# ---- silently dropped a promoted top file's code_block with no eviction  ----

def test_eviction_disabled_without_priority_paths():
    """Backward compatibility: priority_paths defaults to None, which must
    preserve the exact old behavior -- a full budget is a strict no-op."""
    code_blocks = [{"path": f"f{i}.cs", "symbol": "m", "text": "t"} for i in range(6)]
    symbol_hits = [{"label": "Promoted", "path": "new.cs"}]
    new_hits, new_blocks = backfill_missing_code_blocks(
        symbol_hits, code_blocks, {"new.cs"}, None, {"code_block_max_blocks": 6}, fake_enrich_fn
    )
    assert new_blocks == code_blocks, "without priority_paths, must be a strict no-op"


def test_eviction_makes_room_for_promoted_file():
    """The actual bug: budget full, the promoted file IS in the current top-ranked
    window (priority_paths) but none of the existing blocks are -- one non-priority
    block must be evicted to make room for it."""
    code_blocks = [{"path": f"low{i}.cs", "symbol": "m", "text": "t"} for i in range(6)]
    symbol_hits = [{"label": "Promoted", "path": "top.cs"}]
    new_hits, new_blocks = backfill_missing_code_blocks(
        symbol_hits, code_blocks, {"top.cs"}, None, {"code_block_max_blocks": 6},
        fake_enrich_fn, priority_paths={"top.cs"},
    )
    assert len(new_blocks) == 6, f"must stay within budget, got {len(new_blocks)}"
    assert any(b["path"] == "top.cs" for b in new_blocks), "promoted file's block missing after eviction"


def test_priority_blocks_are_never_evicted():
    """If every existing block already belongs to a priority (top-window) file,
    nothing is safe to evict -- must correctly stay a no-op."""
    code_blocks = [{"path": f"top{i}.cs", "symbol": "m", "text": "t"} for i in range(6)]
    symbol_hits = [{"label": "Promoted", "path": "newtop.cs"}]
    priority = {f"top{i}.cs" for i in range(6)} | {"newtop.cs"}
    new_hits, new_blocks = backfill_missing_code_blocks(
        symbol_hits, code_blocks, {"newtop.cs"}, None, {"code_block_max_blocks": 6},
        fake_enrich_fn, priority_paths=priority,
    )
    assert new_blocks == code_blocks, "no evictable candidates -- must remain a no-op"


def _run_all():
    tests = [
        test_pin_promoted_file_gets_code_block,
        test_no_injected_paths_is_noop,
        test_respects_remaining_budget,
        test_already_has_code_block_is_skipped,
        test_eviction_disabled_without_priority_paths,
        test_eviction_makes_room_for_promoted_file,
        test_priority_blocks_are_never_evicted,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL: {t.__name__}: {e}")
    if failed:
        print(f"\n{failed} test(s) FAILED")
        sys.exit(1)
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
