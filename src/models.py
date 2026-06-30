from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextDocument:
    id: str
    title: str
    text: str
    path: str
    source: str
    source_type: str
    kind: str
    module: str | None = None
    pack: str | None = None
    files: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "text": self.text,
            "path": self.path,
            "source": self.source,
            "source_type": self.source_type,
            "kind": self.kind,
            "module": self.module,
            "pack": self.pack,
            "files": self.files,
            "facts": self.facts,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(value: dict[str, Any]) -> "ContextDocument":
        return ContextDocument(
            id=value["id"],
            title=value.get("title", ""),
            text=value.get("text", ""),
            path=value.get("path", ""),
            source=value.get("source", ""),
            source_type=value.get("source_type", ""),
            kind=value.get("kind", ""),
            module=value.get("module"),
            pack=value.get("pack"),
            files=list(value.get("files") or []),
            facts=list(value.get("facts") or []),
            metadata=dict(value.get("metadata") or {}),
        )

