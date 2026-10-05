"""HTTP LLM providers: OpenAI, OpenAI-compatible (Ollama / vLLM / LM Studio ...) and Anthropic. Keys stay server-side."""
from __future__ import annotations

import httpx

from app.ai.providers.base import GenerationRequest, LLMProvider, LLMResult
from app.core.exceptions import ProviderError


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str = "", timeout: int = 60, name: str = "openai"):
        self.name = name
        self.model = model or "gpt-4o-mini"
        self._key = api_key
        self._base = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._timeout = timeout

    def generate(self, req: GenerationRequest) -> LLMResult:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        body = {"model": self.model, "temperature": 0, "max_tokens": req.max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": req.system_prompt}, {"role": "user", "content": req.user_prompt}]}
        try:
            r = httpx.post(f"{self._base}/chat/completions", json=body, headers=headers, timeout=self._timeout)
            r.raise_for_status()
            data = r.json()
            return LLMResult(data["choices"][0]["message"]["content"], self.name, self.model, data.get("model", ""), data.get("usage", {}))
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise ProviderError(f"{self.name} request failed: {type(e).__name__}") from e  # never echo bodies/keys


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, base_url: str = "", timeout: int = 60):
        self.model = model or "claude-sonnet-5-5"
        self._key = api_key
        self._base = (base_url or "https://api.anthropic.com").rstrip("/")
        self._timeout = timeout

    def generate(self, req: GenerationRequest) -> LLMResult:
        headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        body = {"model": self.model, "max_tokens": req.max_tokens, "temperature": 0, "system": req.system_prompt,
                "messages": [{"role": "user", "content": req.user_prompt}]}
        try:
            r = httpx.post(f"{self._base}/v1/messages", json=body, headers=headers, timeout=self._timeout)
            r.raise_for_status()
            data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            return LLMResult(text, self.name, self.model, data.get("model", ""), data.get("usage", {}))
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise ProviderError(f"anthropic request failed: {type(e).__name__}") from e
