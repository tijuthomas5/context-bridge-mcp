from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import AnalysisProvider

_DEFAULT_ENDPOINT = "http://localhost:11434/api/generate"


class OllamaProvider(AnalysisProvider):
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        endpoint = self.config.endpoint or _DEFAULT_ENDPOINT
        num_ctx = int(self.config.extra.get("num_ctx", 8192))
        payload = {
            "model": self.config.model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_ctx": num_ctx,
            },
        }
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
        return str(data.get("response") or "")
