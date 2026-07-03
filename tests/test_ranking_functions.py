"""
Unit tests for ranking-sensitive functions flagged in review as lacking test
coverage: reserve_top_file_code_block_slots() and extract_related_files()'s
anchor-based dependency expansion (src/search.py), and reorder_candidates_by_pins()
(mcp_tools/hybrid_tools.py, the post-fusion pin ordering).

Run directly: python context_bridge/tests/test_ranking_functions.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_CONTEXT_BRIDGE_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _CONTEXT_BRIDGE_ROOT.parent
_SRC = _CONTEXT_BRIDGE_ROOT / "src"
for _p in (str(_PROJECT_ROOT), str(_CONTEXT_BRIDGE_ROOT), str(_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from search import reserve_top_file_code_block_slots, extract_related_files  # noqa: E402
from mcp_tools.hybrid_tools import reorder_candidates_by_pins  # noqa: E402


# ---- reserve_top_file_code_block_slots ----

def test_reserve_moves_top_file_symbols_forward():
    ranked_files = [{"path": "Main.cs"}, {"path": "Other.cs"}]
    symbol_hits = [
        {"path": "Other.cs", "label": "A"},
        {"path": "Other.cs", "label": "B"},
        {"path": "Main.cs", "label": "C"},
        {"path": "Main.cs", "label": "D"},
    ]
    result = reserve_top_file_code_block_slots(symbol_hits, ranked_files, reserve_count=2)
    assert result[0]["label"] == "C" and result[1]["label"] == "D", f"got {[r['label'] for r in result]}"


def test_reserve_noop_when_empty():
    assert reserve_top_file_code_block_slots([], [{"path": "x"}]) == []
    assert reserve_top_file_code_block_slots([{"path": "x"}], []) == [{"path": "x"}]


def test_reserve_caps_at_reserve_count():
    ranked_files = [{"path": "Main.cs"}]
    symbol_hits = [{"path": "Main.cs", "label": str(i)} for i in range(5)]
    result = reserve_top_file_code_block_slots(symbol_hits, ranked_files, reserve_count=2)
    assert [r["label"] for r in result[:2]] == ["0", "1"]
    assert len(result) == 5


# ---- extract_related_files anchor logic ----

def test_dependency_edge_pulls_in_unranked_target():
    """A file connected via a real dependency edge to an already-ranked file
    should surface even if it was never independently keyword-ranked. This is
    the fix from earlier this session (anchor_path in add_related)."""
    results = [{
        "path": "owner.cs",
        "metadata": {
            "dependency_hints": [
                {"source_file": "Main.cs", "target_file": "Helper.cs", "relation": "imports"},
            ]
        },
    }]
    related = extract_related_files(results, preferred_paths={"main.cs"})
    assert "Helper.cs" in related, f"expected Helper.cs pulled in via anchor, got {related}"


def test_unconnected_file_is_excluded():
    """Noise-exclusion regression: a file with no real connection to anything
    ranked must not appear."""
    results = [{
        "path": "owner.cs",
        "metadata": {
            "related_files": ["Random.cs"],
        },
    }]
    related = extract_related_files(results, preferred_paths={"main.cs"})
    assert "Random.cs" not in related, f"unconnected file leaked in: {related}"


# ---- reorder_candidates_by_pins (post-fusion pin ordering) ----

def test_pin_moves_to_front_despite_lower_score():
    """The bug fixed earlier this session: fusion's rank-only RRF formula can
    rank a pinned file below others even though the pin system says it should
    win. This must restore it to the front regardless of fusion score."""
    candidates = [{"path": "Low.cs", "score": 5}, {"path": "Pinned.cs", "score": 1}, {"path": "Mid.cs", "score": 3}]
    result = reorder_candidates_by_pins(candidates, ["Pinned.cs"])
    assert result[0]["path"] == "Pinned.cs", f"got {[r['path'] for r in result]}"
    assert len(result) == 3, "no candidate should be dropped or duplicated"


def test_no_pins_returns_same_list():
    candidates = [{"path": "A.cs"}]
    assert reorder_candidates_by_pins(candidates, []) is candidates


def test_pin_not_in_candidates_is_ignored():
    """A pin never fires a file into the results it didn't already contain --
    it only reorders what fusion already surfaced."""
    candidates = [{"path": "A.cs"}]
    result = reorder_candidates_by_pins(candidates, ["NotPresent.cs"])
    assert result == candidates


def _run_all():
    tests = [
        test_reserve_moves_top_file_symbols_forward,
        test_reserve_noop_when_empty,
        test_reserve_caps_at_reserve_count,
        test_dependency_edge_pulls_in_unranked_target,
        test_unconnected_file_is_excluded,
        test_pin_moves_to_front_despite_lower_score,
        test_no_pins_returns_same_list,
        test_pin_not_in_candidates_is_ignored,
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
