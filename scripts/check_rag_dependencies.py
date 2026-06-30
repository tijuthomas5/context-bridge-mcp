from __future__ import annotations

import importlib.util
import json


def installed(package: str) -> bool:
    return importlib.util.find_spec(package) is not None


def main() -> int:
    payload = {
        "sentence_transformers": installed("sentence_transformers"),
        "torch": installed("torch"),
        "numpy": installed("numpy"),
        "ready_for_semantic_embeddings": installed("sentence_transformers"),
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["ready_for_semantic_embeddings"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
