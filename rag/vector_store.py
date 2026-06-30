from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from .chunker import VectorChunk

_HNSW_MIN_RECORDS = 5000
_hnsw_cache: dict[str, object] = {"index": None, "path": None, "mtime": None}


@dataclass
class VectorRecord:
    chunk: VectorChunk
    vector: list[float]

    def to_dict(self) -> dict[str, object]:
        payload = self.chunk.to_dict()
        payload["vector"] = self.vector
        return payload


@dataclass
class VectorSearchResult:
    record: VectorRecord
    score: float

    def to_dict(self) -> dict[str, object]:
        payload = self.record.chunk.to_dict()
        payload["score"] = round(self.score, 6)
        return payload


@dataclass
class VectorIndexManifest:
    version: int
    created_at: str
    embedding_backend: str
    embedding_model: str
    dimensions: int
    chunk_count: int
    source_document_count: int
    source_index_path: str
    source_index_mtime: float

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "embedding_backend": self.embedding_backend,
            "embedding_model": self.embedding_model,
            "dimensions": self.dimensions,
            "chunk_count": self.chunk_count,
            "source_document_count": self.source_document_count,
            "source_index_path": self.source_index_path,
            "source_index_mtime": self.source_index_mtime,
        }


def write_records(path: Path, records: list[VectorRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


def read_records(path: Path) -> list[VectorRecord]:
    if not path.exists():
        return []
    records: list[VectorRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        chunk = VectorChunk(
            chunk_id=str(payload["chunk_id"]),
            doc_id=str(payload["doc_id"]),
            order=int(payload["order"]),
            text=str(payload["text"]),
            module=payload.get("module"),
            pack=payload.get("pack"),
            source_type=str(payload["source_type"]),
            source=str(payload["source"]),
            path=str(payload["path"]),
            files=list(payload.get("files") or []),
            facts=list(payload.get("facts") or []),
            metadata=dict(payload.get("metadata") or {}),
        )
        records.append(VectorRecord(chunk=chunk, vector=[float(x) for x in payload["vector"]]))
    return records


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _try_hnsw_search(
    records: list[VectorRecord],
    query_vector: list[float],
    top_k: int,
    min_score: float,
    index_path: Path,
) -> list[VectorSearchResult] | None:
    try:
        import hnswlib
        import numpy as np
    except ImportError:
        return None
    path_key = str(index_path)
    current_mtime = index_path.stat().st_mtime if index_path.exists() else None
    if _hnsw_cache["index"] is None or _hnsw_cache["path"] != path_key or _hnsw_cache["mtime"] != current_mtime:
        dims = len(records[0].vector)
        idx = hnswlib.Index(space="cosine", dim=dims)
        idx.init_index(max_elements=len(records), ef_construction=200, M=16)
        import numpy as np
        matrix = np.array([r.vector for r in records], dtype=np.float32)
        idx.add_items(matrix, list(range(len(records))))
        idx.set_ef(50)
        _hnsw_cache.update({"index": idx, "path": path_key, "mtime": current_mtime})
    idx = _hnsw_cache["index"]
    qvec = np.array(query_vector, dtype=np.float32).reshape(1, -1)
    k = min(top_k, len(records))
    labels, distances = idx.knn_query(qvec, k=k)
    results: list[VectorSearchResult] = []
    for label, dist in zip(labels[0], distances[0]):
        score = float(1.0 - dist)
        if score < min_score:
            continue
        results.append(VectorSearchResult(record=records[int(label)], score=score))
    return results


def search_records(
    records: list[VectorRecord],
    query_vector: list[float],
    *,
    top_k: int,
    min_score: float = 0.0,
    index_path: Path | None = None,
) -> list[VectorSearchResult]:
    if not records:
        return []
    if (
        len(records) >= _HNSW_MIN_RECORDS
        and os.environ.get("CONTEXT_BRIDGE_VECTOR_BACKEND", "").lower() == "hnsw"
        and index_path is not None
    ):
        result = _try_hnsw_search(records, query_vector, top_k, min_score, index_path)
        if result is not None:
            return result
    try:
        import numpy as np
        matrix = np.array([r.vector for r in records], dtype=np.float32)
        qvec = np.array(query_vector, dtype=np.float32)
        scores = matrix @ qvec
        mask = scores >= min_score
        indices = np.where(mask)[0]
        if len(indices) == 0:
            return []
        k = min(top_k, len(indices))
        if k < len(indices):
            partitioned = indices[np.argpartition(scores[indices], -k)[-k:]]
        else:
            partitioned = indices
        sorted_idx = partitioned[np.argsort(scores[partitioned])[::-1]]
        return [
            VectorSearchResult(record=records[int(i)], score=float(scores[i]))
            for i in sorted_idx
        ]
    except ImportError:
        scored: list[VectorSearchResult] = []
        for record in records:
            score = cosine_similarity(query_vector, record.vector)
            if score < min_score:
                continue
            scored.append(VectorSearchResult(record=record, score=score))
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[: max(0, top_k)]


def write_manifest(path: Path, manifest: VectorIndexManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")


def read_manifest(path: Path) -> VectorIndexManifest | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return VectorIndexManifest(
        version=int(payload["version"]),
        created_at=str(payload["created_at"]),
        embedding_backend=str(payload["embedding_backend"]),
        embedding_model=str(payload["embedding_model"]),
        dimensions=int(payload["dimensions"]),
        chunk_count=int(payload["chunk_count"]),
        source_document_count=int(payload["source_document_count"]),
        source_index_path=str(payload["source_index_path"]),
        source_index_mtime=float(payload["source_index_mtime"]),
    )
