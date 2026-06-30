from __future__ import annotations

import hashlib
import io
import math
import re
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from typing import Iterable

TOKEN_RE = re.compile(r"[a-z0-9_./:-]+", re.IGNORECASE)


@dataclass
class EmbeddingRequest:
    texts: list[str]
    model: str
    dimensions: int = 384


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    dimensions: int


class EmbeddingBackend:
    name = "unconfigured"

    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        raise NotImplementedError


class NullEmbeddingBackend(EmbeddingBackend):
    name = "null"

    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        raise RuntimeError(
            "No embedding backend configured. "
            "Set embedding_backend to 'hash', 'sentence-transformers', or 'ollama' in the config."
        )


class HashEmbeddingBackend(EmbeddingBackend):
    name = "hash"

    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        dimensions = max(32, int(request.dimensions))
        vectors = [hash_embed(text, dimensions) for text in request.texts]
        return EmbeddingResult(vectors=vectors, model=request.model, dimensions=dimensions)


class SentenceTransformersBackend(EmbeddingBackend):
    name = "sentence-transformers"

    def __init__(self, model_name: str) -> None:
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Use --backend hash or install optional RAG dependencies."
            ) from exc
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self._model = SentenceTransformer(model_name)

    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            vectors = self._model.encode(
                request.texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        output = [[float(value) for value in vector] for vector in vectors]
        dimensions = len(output[0]) if output and output[0] else request.dimensions
        return EmbeddingResult(vectors=output, model=request.model, dimensions=dimensions)


_BACKEND_CACHE: dict[tuple[str, str], EmbeddingBackend] = {}


def create_backend(name: str, model: str) -> EmbeddingBackend:
    normalized = name.strip().lower()
    cache_key = (normalized, model)
    if cache_key in _BACKEND_CACHE:
        return _BACKEND_CACHE[cache_key]
    if normalized in {"hash", "local-hash", "local_hash"}:
        import sys
        print(
            "[ContextBridge] WARNING: using hash embeddings — token matching only, not semantic. "
            "Install sentence-transformers for real semantic vector search.",
            file=sys.stderr,
        )
        backend = HashEmbeddingBackend()
        _BACKEND_CACHE[cache_key] = backend
        return backend
    if normalized in {"sentence-transformers", "sentence_transformers", "local"}:
        backend = SentenceTransformersBackend(model)
        _BACKEND_CACHE[cache_key] = backend
        return backend
    if normalized in {"none", "null"}:
        backend = NullEmbeddingBackend()
        _BACKEND_CACHE[cache_key] = backend
        return backend
    raise ValueError(f"Unknown embedding backend: {name}")


def batch_texts(texts: Iterable[str], batch_size: int) -> list[list[str]]:
    batch: list[str] = []
    output: list[list[str]] = []
    for text in texts:
        batch.append(text)
        if len(batch) >= batch_size:
            output.append(batch)
            batch = []
    if batch:
        output.append(batch)
    return output


def tokenize(value: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(value)]


def hash_embed(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    tokens = tokenize(text)
    for token in tokens:
        add_token(vector, token, 1.0)
    for idx in range(len(tokens) - 1):
        add_token(vector, f"{tokens[idx]} {tokens[idx + 1]}", 0.55)
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [round(value / norm, 6) for value in vector]


def add_token(vector: list[float], token: str, weight: float) -> None:
    digest = hashlib.sha1(token.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:4], "big") % len(vector)
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    vector[bucket] += sign * weight
