from __future__ import annotations

import os
from typing import Any

from .base import AnalysisProvider, ProviderConfig


def create_provider(stage_config: dict[str, Any]) -> AnalysisProvider:
    provider_name = str(stage_config.get("provider") or "ollama").strip().lower()
    model = str(stage_config.get("model") or "")
    endpoint = stage_config.get("endpoint") or None
    timeout = int(stage_config.get("timeout_seconds") or 60)
    temperature = float(stage_config.get("temperature") or 0.1)
    api_key = stage_config.get("api_key") or None

    if provider_name == "ollama":
        from .ollama import OllamaProvider
        api_key = api_key or os.environ.get("OLLAMA_API_KEY")
        extra = {}
        if "num_ctx" in stage_config:
            extra["num_ctx"] = int(stage_config["num_ctx"])
        return OllamaProvider(ProviderConfig(model=model, endpoint=endpoint, api_key=api_key, timeout_seconds=timeout, temperature=temperature, extra=extra))
    if provider_name == "anthropic":
        from .anthropic import AnthropicProvider
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        return AnthropicProvider(ProviderConfig(model=model, endpoint=endpoint, api_key=api_key, timeout_seconds=timeout, temperature=temperature))
    if provider_name == "openai":
        from .openai import OpenAIProvider
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        return OpenAIProvider(ProviderConfig(model=model, endpoint=endpoint, api_key=api_key, timeout_seconds=timeout, temperature=temperature))
    if provider_name == "openrouter":
        from .openrouter import OpenRouterProvider
        api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        return OpenRouterProvider(ProviderConfig(model=model, endpoint=endpoint, api_key=api_key, timeout_seconds=timeout, temperature=temperature))
    raise ValueError(f"Unknown analysis provider: {provider_name!r}. Supported: ollama, anthropic, openai, openrouter")
