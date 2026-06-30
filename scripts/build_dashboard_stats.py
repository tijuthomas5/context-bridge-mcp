from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
USAGE_DIR = PROJECT_ROOT / "context_bridge" / "usage"
TEST_USAGE_DIR = USAGE_DIR / "test"
STATS_PATH = USAGE_DIR / "dashboard_stats.json"
STATS_JS_PATH = USAGE_DIR / "dashboard_stats.js"
BENCHMARK_PATH = PROJECT_ROOT / "context_bridge" / "tests" / "cb_real_world_benchmark_300.json"
BENCHMARK_AUDIT_PATH = PROJECT_ROOT / "context_bridge" / "tests" / "cb_real_world_benchmark_300_audit.json"



def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def tagged_rows(path: Path, source: str) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    tagged: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            tagged.append({**row, "log_source": source})
    return tagged


def percent(value: float) -> float:
    return round(value * 100, 2)


def average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def file_info(path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "exists": exists,
        "path": str(path),
        "size_bytes": path.stat().st_size if exists else 0,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat() if exists else None,
    }


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"error": f"{path.name} is invalid JSON"}


@lru_cache(maxsize=1)
def build_repo_file_index() -> dict[str, list[str]]:
    roots = [PROJECT_ROOT / "main_service", PROJECT_ROOT / "main_ui"]
    index: dict[str, list[str]] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            index.setdefault(path.name.lower(), []).append(str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"))
    return index


@lru_cache(maxsize=1)
def load_benchmark_metadata() -> dict[str, dict[str, Any]]:
    if not BENCHMARK_PATH.exists():
        return {}
    try:
        rows = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        question = str(row.get("question") or "")
        ground_truth = row.get("ground_truth") or {}
        if question:
            output[question] = {
                "question_id": row.get("id"),
                "ground_truth": ground_truth,
            }
    return output


@lru_cache(maxsize=1)
def load_audit_rows() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    data = read_json(BENCHMARK_AUDIT_PATH)
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return {}, {}, {}
    by_event: dict[str, dict[str, Any]] = {}
    by_question: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id") or "")
        question = str(row.get("question") or "")
        if event_id:
            by_event[event_id] = row
        if question:
            by_question[question] = row
    return by_event, by_question, data.get("summary") or {}


@lru_cache(maxsize=256)
def load_pack_source_files_cached(module: str, pack: str) -> tuple[str, ...]:
    if not module or not pack:
        return ()
    pack_root = PROJECT_ROOT / "graphify-out" / module.lower() / pack
    files: set[str] = set()
    if not pack_root.exists():
        return ()
    for source_file in pack_root.rglob("source-files.txt"):
        for line in source_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                files.add(line.strip().replace("\\", "/"))
    return tuple(sorted(files))


def classify_proof_state(
    event: dict[str, Any],
    audit_row: dict[str, Any] | None,
    benchmark_meta: dict[str, Any] | None,
    repo_file_index: dict[str, list[str]],
) -> dict[str, Any]:
    if not audit_row and not benchmark_meta:
        return {
            "proof_state": None,
            "proof_basis": None,
            "proof_reasons": [],
            "confirmed_cb_miss": False,
            "confirmed_graphify_gap": False,
            "invalid_benchmark": False,
        }

    question_id = str((audit_row or {}).get("question_id") or (benchmark_meta or {}).get("question_id") or "")
    ground_truth = (benchmark_meta or {}).get("ground_truth") or {}
    expected_owner_files = list((audit_row or {}).get("expected_owner_files") or ground_truth.get("expected_owner_files") or [])
    expected_pack = str((audit_row or {}).get("expected_pack") or ((ground_truth.get("expected_graphify_packs") or [""])[0] if ground_truth else ""))
    expected_modules = list(ground_truth.get("expected_modules") or [])
    top_files = [str(path or "").replace("\\", "/") for path in (audit_row or {}).get("top_files", [])]
    top_names = {Path(path).name.lower() for path in top_files}

    owner_repo_paths: list[str] = []
    for owner_name in expected_owner_files:
        owner_repo_paths.extend(repo_file_index.get(str(owner_name).lower(), []))
    owner_repo_paths = sorted(set(owner_repo_paths))
    owner_exists = bool(owner_repo_paths)

    pack_source_files: set[str] = set()
    for module in expected_modules:
        pack_source_files.update(load_pack_source_files_cached(str(module), expected_pack))
    owner_in_pack = {
        path for path in owner_repo_paths
        if Path(path).name.lower() in {Path(pack_path).name.lower() for pack_path in pack_source_files}
    }

    verdict = str((audit_row or {}).get("verdict") or "")
    reasons: list[str] = []

    if not owner_exists:
        reasons.append("expected_owner_not_in_repo")
        return {
            "proof_state": "invalid_benchmark",
            "proof_basis": "benchmark+repo",
            "proof_reasons": reasons,
            "confirmed_cb_miss": False,
            "confirmed_graphify_gap": False,
            "invalid_benchmark": True,
            "benchmark_question_id": question_id,
        }

    if expected_pack and not owner_in_pack:
        reasons.append("expected_owner_not_in_graphify_pack")
        return {
            "proof_state": "confirmed_graphify_gap",
            "proof_basis": "benchmark+repo+graphify",
            "proof_reasons": reasons,
            "confirmed_cb_miss": False,
            "confirmed_graphify_gap": True,
            "invalid_benchmark": False,
            "benchmark_question_id": question_id,
        }

    if verdict in {"exact", "strong_pass"}:
        reasons.append(f"audit_verdict:{verdict}")
        return {
            "proof_state": "confirmed_good",
            "proof_basis": "benchmark+repo+graphify+retrieval",
            "proof_reasons": reasons,
            "confirmed_cb_miss": False,
            "confirmed_graphify_gap": False,
            "invalid_benchmark": False,
            "benchmark_question_id": question_id,
        }

    if verdict in {"partial", "weak_partial"}:
        reasons.append(f"audit_verdict:{verdict}")
        if any(name in top_names for name in {Path(path).name.lower() for path in owner_in_pack}):
            reasons.append("some_expected_owner_returned")
        else:
            reasons.append("expected_owner_not_returned")
        return {
            "proof_state": "confirmed_partial",
            "proof_basis": "benchmark+repo+graphify+retrieval",
            "proof_reasons": reasons,
            "confirmed_cb_miss": False,
            "confirmed_graphify_gap": False,
            "invalid_benchmark": False,
            "benchmark_question_id": question_id,
        }

    reasons.append(f"audit_verdict:{verdict or 'missing'}")
    reasons.append("expected_owner_in_graphify_but_not_returned")
    return {
        "proof_state": "confirmed_cb_miss",
        "proof_basis": "benchmark+repo+graphify+retrieval",
        "proof_reasons": reasons,
        "confirmed_cb_miss": True,
        "confirmed_graphify_gap": False,
        "invalid_benchmark": False,
        "benchmark_question_id": question_id,
    }


def classify_event_risk(event: dict[str, Any], outcome: dict[str, Any] | None, gap_log: dict[str, Any]) -> dict[str, Any]:
    confidence = float(event.get("confidence") or 0.0)
    analysis_rc = str(event.get("analysis_relevance_check") or "").upper()
    analysis_conf = str(event.get("analysis_confidence") or "").lower()
    analysis_parse_incomplete = bool(event.get("analysis_parse_incomplete"))
    analysis_parse_error = bool(event.get("analysis_parse_error"))
    files_returned = int(event.get("files_returned") or 0)
    symbol_hits = int(event.get("symbol_hits_returned") or 0)
    location_hints = int(event.get("location_hints_returned") or 0)
    dependency_hints = int(event.get("dependency_chain_returned") or 0)
    gap_fired = int(event.get("gap_searches_fired") or 0)
    gap_added = int(event.get("gap_files_added") or 0)
    primary_owner = bool(event.get("primary_owner_present"))
    outcome_name = str((outcome or {}).get("outcome") or "")
    used_suggested = int((outcome or {}).get("used_suggested_files") or 0)
    extra_files = int((outcome or {}).get("extra_files_read") or 0)
    failure_reason = str((outcome or {}).get("failure_reason") or "")
    top_files = [str(path or "").replace("\\", "/").lower() for path in (event.get("top_files") or [])]

    reasons: list[str] = []
    graphify_gap_suspected = False

    if outcome_name == "failed":
        reasons.append("logged_failed")
    if analysis_rc == "FAILED":
        reasons.append("ai_relevance_failed")
    elif analysis_rc == "PARTIAL":
        reasons.append("ai_relevance_partial")
    elif analysis_rc == "PASSED":
        reasons.append("ai_relevance_passed")
    if analysis_conf:
        reasons.append(f"ai_confidence:{analysis_conf}")
    if analysis_parse_error:
        reasons.append("ai_parse_error")
    elif analysis_parse_incomplete:
        reasons.append("ai_parse_incomplete")
    if failure_reason and failure_reason != "none":
        reasons.append(f"failure_reason:{failure_reason}")
    if confidence < 0.70:
        reasons.append("low_confidence")
    elif confidence < 0.85:
        reasons.append("medium_confidence")
    if files_returned <= 3:
        reasons.append("few_files")
    if not primary_owner:
        reasons.append("no_primary_owner")
    if symbol_hits < 8:
        reasons.append("weak_symbol_coverage")
    if location_hints < 4:
        reasons.append("weak_location_coverage")
    if dependency_hints < 3:
        reasons.append("weak_dependency_coverage")
    if gap_fired > 0:
        reasons.append("gap_search_fired")
        if gap_added > 0:
            reasons.append("gap_search_added_files")
        else:
            reasons.append("gap_search_found_nothing")
            graphify_gap_suspected = True
    if outcome_name == "success" and used_suggested == 0 and extra_files == 0:
        reasons.append("logged_success_but_zero_usage")

    backend_hits = sum(1 for path in top_files[:10] if path.startswith("main_service/"))
    frontend_hits = sum(1 for path in top_files[:10] if path.startswith("main_ui/"))
    if backend_hits >= 8 and frontend_hits == 0:
        reasons.append("backend_heavy_top_files")
    elif frontend_hits >= 8 and backend_hits == 0:
        reasons.append("frontend_heavy_top_files")

    gap_log_timestamp = parse_time(gap_log.get("timestamp"))
    event_timestamp = parse_time(event.get("timestamp"))
    latest_gap_matches = (
        gap_log_timestamp is not None
        and event_timestamp is not None
        and abs((gap_log_timestamp - event_timestamp).total_seconds()) <= 900
    )
    if latest_gap_matches and int(gap_log.get("gaps_fired") or 0) > 0:
        reasons.append("latest_gap_log_present")
        if int(gap_log.get("files_added") or 0) > 0:
            reasons.append("latest_gap_log_added_files")
        else:
            graphify_gap_suspected = True

    if outcome_name == "failed" or analysis_rc == "FAILED" or confidence < 0.60 or (not primary_owner and symbol_hits < 5):
        risk_state = "likely_retrieval_miss"
        action_label = "improve query/profile"
    elif analysis_parse_error or analysis_parse_incomplete:
        risk_state = "needs_review"
        action_label = "review AI output"
    elif analysis_rc == "PARTIAL":
        risk_state = "needs_review"
        action_label = "review owner files"
    elif graphify_gap_suspected or (gap_fired > 0 and gap_added == 0):
        risk_state = "likely_graphify_gap"
        action_label = "improve graphify pack"
    elif (
        confidence >= 0.88
        and primary_owner
        and symbol_hits >= 20
        and location_hints >= 8
        and dependency_hints >= 5
        and gap_fired == 0
        and outcome_name != "failed"
        and "logged_success_but_zero_usage" not in reasons
    ):
        risk_state = "likely_good"
        action_label = "trust result"
    else:
        risk_state = "needs_review"
        action_label = "review owner files"

    return {
        "risk_state": risk_state,
        "risk_reasons": reasons,
        "action_label": action_label,
        "owner_strength": "strong" if primary_owner and confidence >= 0.88 else "weak" if not primary_owner else "medium",
        "evidence_strength": (
            "strong" if symbol_hits >= 20 and location_hints >= 8 and dependency_hints >= 5
            else "medium" if symbol_hits >= 8 and location_hints >= 4
            else "weak"
        ),
        "graphify_gap_suspected": graphify_gap_suspected,
        "latest_gap_log_matches": latest_gap_matches,
    }


def build_index_health() -> dict[str, Any]:
    keyword_index = PROJECT_ROOT / "context_bridge" / "data" / "context_index.json"
    hash_index = PROJECT_ROOT / "context_bridge" / "data" / "vector_index.jsonl"
    hash_meta = PROJECT_ROOT / "context_bridge" / "data" / "vector_meta.json"
    semantic_index = PROJECT_ROOT / "context_bridge" / "data" / "vector_index.semantic.jsonl"
    semantic_meta = PROJECT_ROOT / "context_bridge" / "data" / "vector_meta.semantic.json"
    return {
        "keyword": {
            **file_info(keyword_index),
            "kind": "keyword_graphify",
        },
        "hybrid_hash": {
            **file_info(hash_index),
            "kind": "hash_vector",
            "manifest": read_json(hash_meta),
        },
        "hybrid_semantic": {
            **file_info(semantic_index),
            "kind": "semantic_vector",
            "manifest": read_json(semantic_meta),
        },
    }


def event_mode(event: dict[str, Any]) -> str:
    mode = str(event.get("retrieval_mode") or "").strip()
    if mode:
        if mode in {"semantic", "semantic_hash"}:
            return "hybrid_semantic"
        return mode
    tool = event.get("tool")
    if tool == "search_context_hybrid":
        backend = str(event.get("embedding_backend") or "").lower()
        return "hybrid_semantic" if backend == "sentence-transformers" else "hybrid_hash"
    if tool in {"search_context", "find_related_files", "find_code_locations", "get_graphify_pack", "get_module_summary"}:
        return "keyword"
    return "other"


def build_mode_stats(events: list[dict[str, Any]], outcomes_by_event: dict[str, dict[str, Any]]) -> dict[str, Any]:
    mode_rows: dict[str, list[dict[str, Any]]] = {"keyword": [], "hybrid_hash": [], "hybrid_semantic": [], "other": []}
    for event in events:
        mode_rows.setdefault(event_mode(event), []).append(event)

    output: dict[str, Any] = {}
    for mode, rows in mode_rows.items():
        outcomes = [outcomes_by_event.get(row.get("event_id")) for row in rows]
        outcomes = [item for item in outcomes if item]
        outcome_counts = Counter(item.get("outcome", "unknown") for item in outcomes)
        vector_counts = [float(row.get("vector_candidate_count") or 0) for row in rows]
        suppressed_counts = [float(row.get("suppressed_vector_count") or 0) for row in rows]
        primary_owner_present = [1.0 for row in rows if row.get("primary_owner_present")]
        symbol_hit_counts = [float(row.get("symbol_hits_returned") or 0) for row in rows]
        location_hint_counts = [float(row.get("location_hints_returned") or 0) for row in rows]
        dependency_counts = [float(row.get("dependency_chain_returned") or 0) for row in rows]
        output[mode] = {
            "event_count": len(rows),
            "outcome_count": len(outcomes),
            "success_count": outcome_counts.get("success", 0),
            "partial_count": outcome_counts.get("partial", 0),
            "failed_count": outcome_counts.get("failed", 0),
            "success_rate_percent": percent(outcome_counts.get("success", 0) / len(outcomes)) if outcomes else 0.0,
            "average_confidence": average([
                float(row["confidence"])
                for row in rows
                if isinstance(row.get("confidence"), (int, float))
            ]),
            "average_files_returned": average([float(row.get("files_returned", 0) or 0) for row in rows]),
            "average_vector_candidates": average(vector_counts),
            "average_suppressed_vectors": average(suppressed_counts),
            "primary_owner_rate_percent": percent(sum(primary_owner_present) / len(rows)) if rows else 0.0,
            "average_symbol_hits": average(symbol_hit_counts),
            "average_location_hints": average(location_hint_counts),
            "average_dependency_hints": average(dependency_counts),
            "suppression_rate_percent": percent(sum(suppressed_counts) / sum(vector_counts)) if sum(vector_counts) else 0.0,
            "recent_events": rows[-10:],
        }
    return output


def build_code_location_stats(events: list[dict[str, Any]], outcomes_by_event: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = [event for event in events if event.get("tool") == "find_code_locations"]
    outcomes = [outcomes_by_event.get(row.get("event_id")) for row in rows]
    outcomes = [item for item in outcomes if item]
    outcome_counts = Counter(item.get("outcome", "unknown") for item in outcomes)
    return {
        "call_count": len(rows),
        "outcome_count": len(outcomes),
        "success_count": outcome_counts.get("success", 0),
        "partial_count": outcome_counts.get("partial", 0),
        "failed_count": outcome_counts.get("failed", 0),
        "success_rate_percent": percent(outcome_counts.get("success", 0) / len(outcomes)) if outcomes else 0.0,
        "average_confidence": average([
            float(row["confidence"])
            for row in rows
            if isinstance(row.get("confidence"), (int, float))
        ]),
        "primary_owner_rate_percent": percent(sum(1 for row in rows if row.get("primary_owner_present")) / len(rows)) if rows else 0.0,
        "average_symbol_hits": average([float(row.get("symbol_hits_returned", 0) or 0) for row in rows]),
        "average_location_hints": average([float(row.get("location_hints_returned", 0) or 0) for row in rows]),
        "average_dependency_hints": average([float(row.get("dependency_chain_returned", 0) or 0) for row in rows]),
        "average_related_files": average([float(row.get("related_files_returned", 0) or 0) for row in rows]),
        "average_code_blocks": average([float(row.get("code_blocks_returned", 0) or 0) for row in rows]),
        "recent_events": rows[-10:],
    }


def _collect_jsonl_files(directory: Path, pattern: str) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob(pattern))


def _tagged_dir(directory: Path, pattern: str, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _collect_jsonl_files(directory, pattern):
        rows.extend(tagged_rows(path, source))
    return rows


def build_stats() -> dict[str, Any]:
    events = _tagged_dir(USAGE_DIR, "events*.jsonl", "main") + _tagged_dir(TEST_USAGE_DIR, "events*.jsonl", "test")
    outcomes = _tagged_dir(USAGE_DIR, "outcomes*.jsonl", "main") + _tagged_dir(TEST_USAGE_DIR, "outcomes*.jsonl", "test")
    events.sort(key=lambda item: str(item.get("timestamp") or ""))
    outcomes.sort(key=lambda item: str(item.get("timestamp") or ""))
    outcomes_by_event = {item.get("event_id"): item for item in outcomes}

    inferred_outcomes: list[dict[str, Any]] = []
    for event in events:
        eid = event.get("event_id")
        if eid and eid not in outcomes_by_event:
            confidence = event.get("confidence")
            files_returned = int(event.get("files_returned") or 0)
            gap_fired = int(event.get("gap_searches_fired") or 0)
            analysis_rc = str(event.get("analysis_relevance_check") or "").upper()
            analysis_parse_incomplete = bool(event.get("analysis_parse_incomplete"))
            if analysis_rc == "FAILED":
                outcome = "failed"
            elif analysis_rc == "PARTIAL":
                outcome = "partial"
            elif files_returned == 0 or (isinstance(confidence, (int, float)) and float(confidence) < 0.45):
                outcome = "failed"
            elif analysis_parse_incomplete:
                outcome = "partial"
            elif gap_fired > 0 and not event.get("primary_owner_present"):
                outcome = "partial"
            else:
                continue  # no signal — leave unrated
            inferred_outcomes.append({
                "outcome_id": f"inferred_{eid}",
                "event_id": eid,
                "timestamp": event.get("timestamp"),
                "outcome": outcome,
                "used_suggested_files": files_returned,
                "extra_files_read": 0,
                "gap_searches_fired": gap_fired,
                "gap_files_added": int(event.get("gap_files_added") or 0),
                "needed_extra_search": gap_fired > 0,
                "missed_files": [],
                "missed_file_count": 0,
                "failure_reason": "none",
                "notes": "",
                "inferred": True,
                "log_source": event.get("log_source", "main"),
            })
            outcomes_by_event[eid] = inferred_outcomes[-1]
    all_outcomes = outcomes + inferred_outcomes
    last_gap_search = read_json(USAGE_DIR / "last_gap_search.json")
    repo_file_index = build_repo_file_index()
    benchmark_meta_by_question = load_benchmark_metadata()
    audit_by_event, audit_by_question, audit_summary = load_audit_rows()
    latest_eval_path = USAGE_DIR / "latest_eval_summary.json"
    latest_eval = {}
    if latest_eval_path.exists():
        try:
            latest_eval = json.loads(latest_eval_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            latest_eval = {"error": "latest_eval_summary.json is invalid JSON"}
    latest_hybrid_eval_path = USAGE_DIR / "latest_hybrid_eval_summary.json"
    latest_hybrid_eval = {}
    if latest_hybrid_eval_path.exists():
        try:
            latest_hybrid_eval = json.loads(latest_hybrid_eval_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            latest_hybrid_eval = {"error": "latest_hybrid_eval_summary.json is invalid JSON"}
    latest_semantic_hybrid_eval_path = USAGE_DIR / "latest_semantic_hybrid_eval_summary.json"
    latest_semantic_hybrid_eval = {}
    if latest_semantic_hybrid_eval_path.exists():
        try:
            latest_semantic_hybrid_eval = json.loads(latest_semantic_hybrid_eval_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            latest_semantic_hybrid_eval = {"error": "latest_semantic_hybrid_eval_summary.json is invalid JSON"}
    latest_code_location_eval_path = USAGE_DIR / "latest_code_location_eval_summary.json"
    latest_code_location_eval = {}
    if latest_code_location_eval_path.exists():
        try:
            latest_code_location_eval = json.loads(latest_code_location_eval_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            latest_code_location_eval = {"error": "latest_code_location_eval_summary.json is invalid JSON"}
    latest_graphify_enrichment_report_path = USAGE_DIR / "latest_graphify_enrichment_report.json"
    latest_graphify_enrichment_report = {}
    if latest_graphify_enrichment_report_path.exists():
        try:
            latest_graphify_enrichment_report = json.loads(
                latest_graphify_enrichment_report_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError:
            latest_graphify_enrichment_report = {"error": "latest_graphify_enrichment_report.json is invalid JSON"}
    latest_full_quality_suite_path = USAGE_DIR / "latest_full_quality_suite.json"
    latest_full_quality_suite = {}
    if latest_full_quality_suite_path.exists():
        try:
            latest_full_quality_suite = json.loads(latest_full_quality_suite_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            latest_full_quality_suite = {"error": "latest_full_quality_suite.json is invalid JSON"}
    elif (PROJECT_ROOT / "context_bridge" / "usage" / "latest_full_quality_suite.json").exists():
        try:
            latest_full_quality_suite = json.loads(
                (PROJECT_ROOT / "context_bridge" / "usage" / "latest_full_quality_suite.json").read_text(encoding="utf-8")
            )
        except json.JSONDecodeError:
            latest_full_quality_suite = {"error": "latest_full_quality_suite.json is invalid JSON"}

    tool_counts = Counter(event.get("tool", "unknown") for event in events)
    mode_counts = Counter(event_mode(event) for event in events)
    source_event_counts = Counter(event.get("log_source", "unknown") for event in events)
    source_outcome_counts = Counter(outcome.get("log_source", "unknown") for outcome in all_outcomes)
    outcome_counts = Counter(outcome.get("outcome", "unknown") for outcome in all_outcomes)
    failure_counts = Counter(outcome.get("failure_reason", "unknown") for outcome in all_outcomes)
    confidence_values = [
        float(event["confidence"])
        for event in events
        if isinstance(event.get("confidence"), (int, float))
    ]
    files_returned_values = [
        float(event.get("files_returned", 0) or 0)
        for event in events
        if event.get("tool") in {"search_context", "find_related_files", "get_graphify_pack", "get_module_summary"}
    ]
    extra_files = [float(outcome.get("extra_files_read", 0) or 0) for outcome in all_outcomes]
    used_files = [float(outcome.get("used_suggested_files", 0) or 0) for outcome in all_outcomes]
    extra_search_count = sum(1 for outcome in all_outcomes if outcome.get("needed_extra_search"))

    estimated_baseline_files = sum(
        (outcome.get("used_suggested_files", 0) or 0) + (outcome.get("extra_files_read", 0) or 0) + 10
        for outcome in all_outcomes
    )
    estimated_actual_files = sum(
        (outcome.get("used_suggested_files", 0) or 0) + (outcome.get("extra_files_read", 0) or 0)
        for outcome in all_outcomes
    )
    file_reduction = 0.0
    if estimated_baseline_files:
        file_reduction = 1 - (estimated_actual_files / estimated_baseline_files)

    # --- Measured token savings (char-based proxy, no external deps) ---
    # For each event: compare chars CB DELIVERED (context_chars) against the full
    # contents of the files it pointed to (top_files, read from disk). Using chars
    # as a token proxy is accurate for a RATIO because tokenizer bias cancels out.
    # Baseline = "reading the full files CB surfaced" (the conservative, fair baseline
    # from the literature — NOT the whole repo, which would inflate savings).
    def _file_chars(rel_path: Any) -> int:
        try:
            p = PROJECT_ROOT / str(rel_path).replace("\\", "/")
            if not p.exists() or not p.is_file():
                return 0
            return len(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return 0

    total_context_chars = 0
    total_baseline_chars = 0
    measured_event_count = 0
    token_savings_rows: list[dict[str, Any]] = []
    for event in events:
        context_chars = event.get("context_chars")
        top = event.get("top_files") or []
        if context_chars is None or not top:
            continue
        baseline = sum(_file_chars(f) for f in top)
        if baseline <= 0:
            continue
        total_context_chars += int(context_chars)
        total_baseline_chars += baseline
        measured_event_count += 1
        token_savings_rows.append({
            "query": event.get("query"),
            "delivered_chars": int(context_chars),
            "baseline_chars": baseline,
            "saved_percent": round(100.0 * (1 - context_chars / baseline), 1),
        })
    measured_token_savings = 0.0
    if total_baseline_chars > 0:
        measured_token_savings = max(0.0, min(99.9, 100.0 * (1 - total_context_chars / total_baseline_chars)))
    token_savings_breakdown = {
        "overall_saved_percent": round(measured_token_savings, 2),
        "total_delivered_chars": total_context_chars,
        "total_baseline_chars": total_baseline_chars,
        "sample_size": measured_event_count,
        "baseline": "full contents of the files CB returned (top files)",
        "formula": "1 - (delivered chars / full-file chars), summed across queries",
        "rows": token_savings_rows,
    }

    events_with_top_files = [
        event
        for event in events
        if event.get("top_files")
    ]
    missed_files: list[dict[str, Any]] = []
    for outcome in all_outcomes:
        outcome_time = parse_time(outcome.get("timestamp"))
        for missed in outcome.get("missed_files", []) or []:
            missed_norm = str(missed).replace("\\", "/").lower()
            resolved_by = None
            for event in events_with_top_files:
                event_time = parse_time(event.get("timestamp"))
                if outcome_time and event_time and event_time <= outcome_time:
                    continue
                top_files = [
                    str(path).replace("\\", "/").lower()
                    for path in event.get("top_files", []) or []
                ]
                if missed_norm in top_files:
                    resolved_by = event
                    break
            missed_files.append({
                "file": missed,
                "event_id": outcome.get("event_id"),
                "failure_reason": outcome.get("failure_reason"),
                "status": "resolved_by_later_search" if resolved_by else "open_or_not_retested",
                "resolved_by_event": resolved_by.get("event_id") if resolved_by else None,
                "resolved_at": resolved_by.get("timestamp") if resolved_by else None,
            })

    failed_queries: list[dict[str, Any]] = []
    for event in events:
        outcome = outcomes_by_event.get(event.get("event_id"))
        if not outcome or outcome.get("outcome") != "failed":
            continue
        failed_queries.append({
            "event_id": event.get("event_id"),
            "query": event.get("query"),
            "tool": event.get("tool"),
            "failure_reason": outcome.get("failure_reason"),
            "notes": outcome.get("notes", ""),
        })

    low_confidence = [
        {
            "event_id": event.get("event_id"),
            "query": event.get("query"),
            "tool": event.get("tool"),
            "confidence": event.get("confidence"),
        }
        for event in events
        if isinstance(event.get("confidence"), (int, float)) and float(event["confidence"]) < 0.45
    ][:25]

    recent_events: list[dict[str, Any]] = []
    risk_state_counts: Counter[str] = Counter()
    action_label_counts: Counter[str] = Counter()
    proof_state_counts: Counter[str] = Counter()
    for event in events:
        outcome = outcomes_by_event.get(event.get("event_id"))
        risk = classify_event_risk(event, outcome, last_gap_search)
        benchmark_meta = benchmark_meta_by_question.get(str(event.get("query") or ""))
        audit_row = audit_by_event.get(str(event.get("event_id") or "")) or audit_by_question.get(str(event.get("query") or ""))
        proof = classify_proof_state(event, audit_row, benchmark_meta, repo_file_index)
        risk_state_counts[risk["risk_state"]] += 1
        action_label_counts[risk["action_label"]] += 1
        if proof.get("proof_state"):
            proof_state_counts[str(proof["proof_state"])] += 1
        recent_events.append({
            **event,
            "outcome": (outcome or {}).get("outcome"),
            "failure_reason": (outcome or {}).get("failure_reason"),
            "outcome_notes": (outcome or {}).get("notes"),
            **risk,
            **proof,
        })

    stats = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_tool_calls": len(events),
        "total_search_context_calls": tool_counts.get("search_context", 0),
        "total_tasks_with_outcomes": len(all_outcomes),
        "total_recorded_outcomes": len(outcomes),
        "total_inferred_outcomes": len(inferred_outcomes),
        "total_gap_searches": sum(int(e.get("gap_searches_fired") or 0) for e in events),
        "total_gap_files_added": sum(int(e.get("gap_files_added") or 0) for e in events),
        "gap_search_rate_percent": percent(
            sum(1 for e in events if int(e.get("gap_searches_fired") or 0) > 0) / len(events)
        ) if events else 0.0,
        "tool_counts": dict(tool_counts),
        "mode_counts": dict(mode_counts),
        "log_source_counts": {
            "events": dict(source_event_counts),
            "outcomes": dict(source_outcome_counts),
        },
        "mode_stats": build_mode_stats(events, outcomes_by_event),
        "code_location_stats": build_code_location_stats(events, outcomes_by_event),
        "outcome_counts": dict(outcome_counts),
        "failure_reason_counts": dict(failure_counts),
        "risk_state_counts": dict(risk_state_counts),
        "action_label_counts": dict(action_label_counts),
        "proof_state_counts": dict(proof_state_counts),
        "success_rate_percent": percent(outcome_counts.get("success", 0) / len(all_outcomes)) if all_outcomes else 0.0,
        "partial_rate_percent": percent(outcome_counts.get("partial", 0) / len(all_outcomes)) if all_outcomes else 0.0,
        "failed_rate_percent": percent(outcome_counts.get("failed", 0) / len(all_outcomes)) if all_outcomes else 0.0,
        "average_confidence": average(confidence_values),
        "average_files_returned": average(files_returned_values),
        "average_used_suggested_files": average(used_files),
        "average_extra_files_read": average(extra_files),
        "extra_search_count": extra_search_count,
        "extra_search_rate_percent": percent(extra_search_count / len(all_outcomes)) if all_outcomes else 0.0,
        "estimated_file_read_reduction_percent": percent(file_reduction),
        "estimated_token_savings_percent": round(measured_token_savings, 2),
        "token_savings_method": "measured_char_ratio_vs_full_files",
        "token_savings_sample_size": measured_event_count,
        "token_savings_breakdown": token_savings_breakdown,
        "missed_files": missed_files,
        "failed_queries": failed_queries,
        "low_confidence_searches": low_confidence,
        "latest_ranking_profile": next(
            (
                event.get("ranking_profile")
                for event in reversed(events)
                if event.get("ranking_profile")
            ),
            None,
        ),
        "latest_eval": latest_eval,
        "latest_hybrid_eval": latest_hybrid_eval,
        "latest_semantic_hybrid_eval": latest_semantic_hybrid_eval,
        "latest_code_location_eval": latest_code_location_eval,
        "latest_graphify_enrichment_report": latest_graphify_enrichment_report,
        "latest_full_quality_suite": latest_full_quality_suite,
        "benchmark_audit_summary": audit_summary,
        "last_gap_search": last_gap_search,
        "index_health": build_index_health(),
        "pipeline_stats": build_pipeline_stats(),
        "recent_events": recent_events,
        "recent_outcomes": all_outcomes,
        "recent_code_location_events": [event for event in events if event.get("tool") == "find_code_locations"],
    }
    return stats


def build_pipeline_stats() -> dict[str, Any]:
    """
    Read the active pipeline mode and last run details from config + usage logs.
    Shown in dashboard so users know which pipeline steps ran on the last query.
    """
    stats: dict[str, Any] = {
        "pipeline_mode": "unknown",
        "cb_pre_validate": False,
        "self_reflection": False,
        "max_gap_iterations": 2,
        "last_run": None,
    }
    try:
        import json as _json
        config_name = "config.hybrid.json"
        config_path = PROJECT_ROOT / "context_bridge" / config_name
        if config_path.exists():
            raw = _json.loads(config_path.read_text(encoding="utf-8"))
            stage = (raw.get("pipeline") or {}).get("analysis_stage") or {}
            stats["pipeline_mode"] = str(stage.get("pipeline_mode") or "validated")
            stats["cb_pre_validate"] = bool(stage.get("cb_pre_validate", False))
            stats["self_reflection"] = bool(stage.get("self_reflection", False))
            stats["max_gap_iterations"] = int(stage.get("max_gap_iterations") or 2)
            stats["local_ai_enabled"] = bool(stage.get("enabled", False))
            stats["local_ai_provider"] = str(stage.get("provider") or "")
    except Exception:
        pass

    # Last pipeline run details from Qwen output log
    try:
        import json as _json
        log_path = PROJECT_ROOT / "context_bridge" / "usage" / "last_qwen_output.json"
        if log_path.exists():
            last = _json.loads(log_path.read_text(encoding="utf-8"))
            parsed = last.get("parsed") or {}
            stats["last_run"] = {
                "timestamp": last.get("timestamp"),
                "latency_ms": last.get("latency_ms"),
                "relevance_check": (parsed.get("relevance_check") or ""),
                "confidence": (parsed.get("confidence") or ""),
                "topic_count": len(parsed.get("topics") or []),
                "parse_incomplete": bool(parsed.get("parse_incomplete")),
                "gap_searches_fired": parsed.get("gap_searches_fired") or 0,
                "gap_files_added": parsed.get("gap_files_added") or 0,
                "reflection": bool(parsed.get("reflection")),
                "fallback": bool(parsed.get("skipped")),
            }
    except Exception:
        pass

    return stats


def main() -> int:
    USAGE_DIR.mkdir(parents=True, exist_ok=True)
    stats = build_stats()
    STATS_PATH.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    STATS_JS_PATH.write_text(
        "window.CONTEXT_BRIDGE_STATS = "
        + json.dumps(stats, indent=2, ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "stats_path": str(STATS_PATH),
        "stats_js_path": str(STATS_JS_PATH),
        "total_tool_calls": stats["total_tool_calls"],
        "total_tasks_with_outcomes": stats["total_tasks_with_outcomes"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
