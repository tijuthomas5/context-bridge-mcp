"""
sync_custom_packs.py -- detect drift and rebuild only the ContextBridge
custom packs that are actually stale. Generic: works on any project.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
GRAPHIFY_OUT = ROOT / "graphify-out"
BUILD_PACK_SCRIPT = Path(__file__).resolve().parent / "build_pack.py"
PROJECT_MAP_PATH = Path(__file__).resolve().parent / "project_map.json"


def load_excluded_modules():
    if not PROJECT_MAP_PATH.exists():
        return set()
    try:
        data = json.loads(PROJECT_MAP_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return set(data.get("excluded_modules", []))


def discover_packs():
    excluded_modules = load_excluded_modules()
    packs = []
    if not GRAPHIFY_OUT.exists():
        return packs
    for module_dir in GRAPHIFY_OUT.iterdir():
        if not module_dir.is_dir() or module_dir.name in excluded_modules:
            continue
        for pack_dir in module_dir.iterdir():
            if pack_dir.is_dir() and (pack_dir / "raw" / "source-files.txt").exists():
                packs.append(pack_dir)
    return sorted(packs)


def hash_file(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def safe_repo_path(rel):
    """Resolve rel against ROOT and refuse it if it escapes ROOT.

    See scan_repo.py's safe_repo_path for why: source-files.txt is trusted
    config with no path validation otherwise, and a crafted '..\\..\\x' entry
    would let this read/hash a file outside the repo. Returns None instead of
    raising so callers can surface it as a normal stale-reason.
    """
    root_resolved = ROOT.resolve()
    candidate = (root_resolved / rel).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def pack_is_stale(pack_dir):
    raw_dir = pack_dir / "raw"
    source_list = raw_dir / "source-files.txt"
    manifest_path = raw_dir / "manifest.json"
    lines = source_list.read_text(encoding="utf-8").splitlines()
    source_files = [ln.strip() for ln in lines if ln.strip()]

    if not manifest_path.exists():
        return True, "no manifest.json yet"

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True, "manifest.json is not valid JSON"

    is_hash_manifest = bool(manifest) and all(isinstance(v, dict) for v in manifest.values())
    if not is_hash_manifest:
        return True, "manifest.json is not a hash manifest yet (will be created on next build)"

    by_suffix = {}
    for key, value in manifest.items():
        norm_key = key.replace(chr(92), "/")
        by_suffix[norm_key] = value.get("hash")

    for rel in source_files:
        src = safe_repo_path(rel)
        if src is None:
            return True, "REFUSED -- source-files.txt entry escapes repo root: " + rel
        if not src.exists():
            return True, "source file missing on disk: " + rel
        rel_norm = rel.replace(chr(92), "/")
        matched = None
        for suffix, h in by_suffix.items():
            if suffix.endswith(rel_norm):
                matched = h
                break
        if matched is None:
            return True, "file not present in manifest: " + rel
        if matched != hash_file(src):
            return True, "content changed since last build: " + rel

    return False, "up to date"


def run_build(pack_dir):
    print("-- building " + str(pack_dir.relative_to(ROOT)) + " --")
    result = subprocess.run(
        [sys.executable, str(BUILD_PACK_SCRIPT), str(pack_dir), "--repo-root", str(ROOT)],
        cwd=str(ROOT),
    )
    return result.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reindex", action="store_true")
    args = parser.parse_args()

    packs = discover_packs()

    stale_packs = []
    up_to_date_count = 0

    for pack_dir in packs:
        key = pack_dir.parent.name + "/" + pack_dir.name
        stale, reason = pack_is_stale(pack_dir)
        if not stale:
            up_to_date_count += 1
            continue
        stale_packs.append((pack_dir, key, reason))

    print(
        "Packs checked: "
        + str(len(packs))
        + " up to date: "
        + str(up_to_date_count)
        + " stale: "
        + str(len(stale_packs))
    )

    if stale_packs:
        print("Stale packs:")
        for _, key, reason in stale_packs:
            print("  - " + key + ": " + reason)

    if args.dry_run:
        return 0

    for pack_dir, key, _ in stale_packs:
        code = run_build(pack_dir)
        if code != 0:
            print("[FAILED] " + key + " exited with code " + str(code))
            return code

    if args.reindex:
        setup_script = ROOT / "context_bridge" / "scripts" / "setup_context_bridge.py"
        print("-- reindexing via " + str(setup_script.relative_to(ROOT)) + " --")
        result = subprocess.run([sys.executable, str(setup_script)], cwd=str(ROOT))
        return result.returncode

    return 0


if __name__ == "__main__":
    sys.exit(main())
