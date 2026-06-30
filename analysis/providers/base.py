from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderConfig:
    model: str
    endpoint: str | None = None
    api_key: str | None = None
    timeout_seconds: int = 60
    temperature: float = 0.1
    extra: dict[str, Any] = field(default_factory=dict)


class AnalysisProvider(ABC):
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Send system+user prompts and return the raw text response."""
        ...
