from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import AnalysisProvider

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
_MAX_TOKENS = 4096


class AnthropicProvider(AnalysisProvider):
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        api_key = self.config.api_key
        if not api_key:
            raise ValueError("Anthropic provider requires api_key in pipeline config or ANTHROPIC_API_KEY env var")
        payload = {
            "model": self.config.model,
            "max_tokens": _MAX_TOKENS,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": self.config.temperature,
        }
        req = urllib.request.Request(
            self.config.endpoint or _API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": _API_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Anthropic request failed: {exc}") from exc
        return str(data["content"][0]["text"])
