from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class ChunkerConfig:
    max_chars: int = 3200
    overlap_chars: int = 200
    min_chunk_chars: int = 200


@dataclass
class VectorChunk:
    chunk_id: str
    doc_id: str
    order: int
    text: str
    module: str | None
    pack: str | None
    source_type: str
    source: str
    path: str
    files: list[str]
    facts: list[str]
    metadata: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "order": self.order,
            "text": self.text,
            "module": self.module,
            "pack": self.pack,
            "source_type": self.source_type,
            "source": self.source,
            "path": self.path,
            "files": self.files,
            "facts": self.facts,
            "metadata": self.metadata,
        }


def chunk_text(
    *,
    doc_id: str,
    text: str,
    module: str | None,
    pack: str | None,
    source_type: str,
    source: str,
    path: str,
    files: list[str],
    facts: list[str],
    metadata: dict[str, object],
    config: ChunkerConfig | None = None,
) -> list[VectorChunk]:
    cfg = config or ChunkerConfig()
    normalized = normalize_text(text)
    if not normalized:
        return []

    chunks: list[VectorChunk] = []
    cursor = 0
    order = 0
    total = len(normalized)
    while cursor < total:
        end = min(total, cursor + cfg.max_chars)
        window = normalized[cursor:end]
        if end < total:
            split = find_split_point(window)
            if split >= cfg.min_chunk_chars:
                window = window[:split]
                end = cursor + split
        chunk_text_value = window.strip()
        if len(chunk_text_value) >= cfg.min_chunk_chars or not chunks:
            chunks.append(
                VectorChunk(
                    chunk_id=f"{doc_id}::chunk::{order}",
                    doc_id=doc_id,
                    order=order,
                    text=chunk_text_value,
                    module=module,
                    pack=pack,
                    source_type=source_type,
                    source=source,
                    path=path,
                    files=list(files),
                    facts=list(facts),
                    metadata=dict(metadata),
                )
            )
            order += 1
        if end >= total:
            break
        cursor = max(end - cfg.overlap_chars, cursor + 1)
    return chunks


def chunk_lines(
    *,
    doc_id: str,
    lines: Iterable[str],
    module: str | None,
    pack: str | None,
    source_type: str,
    source: str,
    path: str,
    files: list[str],
    facts: list[str],
    metadata: dict[str, object],
    config: ChunkerConfig | None = None,
) -> list[VectorChunk]:
    return chunk_text(
        doc_id=doc_id,
        text="\n".join(line.rstrip() for line in lines if line.strip()),
        module=module,
        pack=pack,
        source_type=source_type,
        source=source,
        path=path,
        files=files,
        facts=facts,
        metadata=metadata,
        config=config,
    )


def normalize_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.splitlines() if line.strip()).strip()


def find_split_point(value: str) -> int:
    for marker in ("\n## ", "\n### ", "\n# ", "\n- ", ". ", "\n"):
        idx = value.rfind(marker)
        if idx > 0:
            return idx + len(marker.strip())
    last_period = value.rfind(".", 200)
    if last_period > 0:
        return last_period + 1
    return len(value)
