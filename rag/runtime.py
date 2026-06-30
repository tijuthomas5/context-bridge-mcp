from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .vector_store import VectorIndexManifest, read_manifest


@dataclass
class RuntimeStatus:
    enabled: bool
    mode: str
    vector_index_exists: bool
    vector_index_stale: bool
    manifest: VectorIndexManifest | None
    message: str


class RAGRuntime:
    def __init__(
        self,
        *,
        enabled: bool,
        mode: str,
        vector_manifest_path: Path,
        source_index_path: Path,
    ) -> None:
        self.enabled = enabled
        self.mode = mode
        self.vector_manifest_path = vector_manifest_path
        self.source_index_path = source_index_path

    def status(self) -> RuntimeStatus:
        manifest = read_manifest(self.vector_manifest_path)
        exists = manifest is not None
        stale = False
        if manifest and self.source_index_path.exists():
            source_mtime = self.source_index_path.stat().st_mtime
            stale = source_mtime > manifest.source_index_mtime + 1
        if not self.enabled:
            return RuntimeStatus(
                enabled=False,
                mode=self.mode,
                vector_index_exists=exists,
                vector_index_stale=stale,
                manifest=manifest,
                message="RAG runtime is disabled.",
            )
        if not exists:
            return RuntimeStatus(
                enabled=True,
                mode=self.mode,
                vector_index_exists=False,
                vector_index_stale=False,
                manifest=None,
                message="RAG runtime is enabled, but no vector index exists yet.",
            )
        if stale:
            return RuntimeStatus(
                enabled=True,
                mode=self.mode,
                vector_index_exists=True,
                vector_index_stale=True,
                manifest=manifest,
                message="Vector index exists but is stale relative to the keyword index.",
            )
        return RuntimeStatus(
            enabled=True,
            mode=self.mode,
            vector_index_exists=True,
            vector_index_stale=False,
            manifest=manifest,
            message="RAG runtime is ready.",
        )
