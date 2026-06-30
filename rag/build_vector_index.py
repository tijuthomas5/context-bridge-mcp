from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "context_bridge" / "src"))

from models import ContextDocument  # noqa: E402

from context_bridge.rag.chunker import ChunkerConfig, VectorChunk, chunk_text  # noqa: E402
from context_bridge.rag.embeddings import EmbeddingRequest, batch_texts, create_backend  # noqa: E402
from context_bridge.rag.vector_store import VectorIndexManifest, VectorRecord, write_manifest, write_records  # noqa: E402


def load_keyword_index(index_path: Path) -> dict[str, object]:
    if not index_path.exists():
        raise FileNotFoundError(f"Keyword index not found: {index_path}")
    return json.loads(index_path.read_text(encoding="utf-8"))


def build_chunks(documents: list[ContextDocument], chunker_config: ChunkerConfig) -> list[VectorChunk]:
    chunks: list[VectorChunk] = []
    for doc in documents:
        if not doc.text.strip():
            continue
        chunks.extend(
            chunk_text(
                doc_id=doc.id,
                text=doc.text,
                module=doc.module,
                pack=doc.pack,
                source_type=doc.source_type,
                source=doc.source,
                path=doc.path,
                files=doc.files,
                facts=doc.facts,
                metadata=doc.metadata,
                config=chunker_config,
            )
        )
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the local ContextBridge vector index.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--chunks-output", default="context_bridge/data/vector_chunks.jsonl")
    parser.add_argument("--index-output", default="context_bridge/data/vector_index.jsonl")
    parser.add_argument("--manifest-output", default="context_bridge/data/vector_meta.json")
    parser.add_argument("--backend", default="hash")
    parser.add_argument("--model", default="hash-384")
    parser.add_argument("--dimensions", type=int, default=384)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    config_path = PROJECT_ROOT / "context_bridge" / args.config
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    index_rel = Path("context_bridge") / str(config.get("index_path", "data/context_index.json"))
    index_path = PROJECT_ROOT / index_rel
    payload = load_keyword_index(index_path)
    documents = [ContextDocument.from_dict(item) for item in payload.get("documents", [])]
    chunks = build_chunks(documents, ChunkerConfig())

    chunks_path = PROJECT_ROOT / args.chunks_output
    chunks_path.parent.mkdir(parents=True, exist_ok=True)
    with chunks_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")

    backend = create_backend(args.backend, args.model)
    records: list[VectorRecord] = []
    for batch in batch_texts((chunk.text for chunk in chunks), max(1, args.batch_size)):
        result = backend.embed(
            EmbeddingRequest(
                texts=batch,
                model=args.model,
                dimensions=args.dimensions,
            )
        )
        start = len(records)
        for offset, vector in enumerate(result.vectors):
            records.append(VectorRecord(chunk=chunks[start + offset], vector=vector))

    index_path_out = PROJECT_ROOT / args.index_output
    manifest_path = PROJECT_ROOT / args.manifest_output
    write_records(index_path_out, records)
    dimensions = len(records[0].vector) if records else 0
    manifest = VectorIndexManifest(
        version=1,
        created_at=datetime.now(timezone.utc).isoformat(),
        embedding_backend=backend.name,
        embedding_model=args.model,
        dimensions=dimensions,
        chunk_count=len(chunks),
        source_document_count=len(documents),
        source_index_path=str(index_path),
        source_index_mtime=index_path.stat().st_mtime,
    )
    write_manifest(manifest_path, manifest)

    print(
        json.dumps(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "keyword_index_path": str(index_path),
                "chunks_path": str(chunks_path),
                "vector_index_path": str(index_path_out),
                "manifest_path": str(manifest_path),
                "document_count": len(documents),
                "chunk_count": len(chunks),
                "embedding_backend": backend.name,
                "embedding_model": args.model,
                "dimensions": dimensions,
                "phase": "phase-2-vector-index",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
