from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import AnalysisProvider

_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(AnalysisProvider):
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        api_key = self.config.api_key
        if not api_key:
            raise ValueError("OpenAI provider requires api_key in pipeline config or OPENAI_API_KEY env var")
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
        }
        req = urllib.request.Request(
            self.config.endpoint or _API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc
        return str(data["choices"][0]["message"]["content"])
