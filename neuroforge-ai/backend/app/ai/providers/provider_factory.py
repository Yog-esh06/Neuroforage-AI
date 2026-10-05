"""Select the LLM provider from environment configuration (LLM_PROVIDER / LLM_MODEL / LLM_API_KEY / LLM_BASE_URL)."""
from __future__ import annotations

import logging

from app.ai.providers.base import LLMProvider
from app.ai.providers.extractive import ExtractiveProvider
from app.ai.providers.http_providers import AnthropicProvider, OpenAIProvider
from app.core.config import get_settings

log = logging.getLogger(__name__)
_cache: dict[tuple, LLMProvider] = {}


def get_provider() -> LLMProvider:
    s = get_settings()
    key = (s.llm_provider, s.llm_model, s.llm_base_url, bool(s.llm_api_key))
    if key in _cache:
        return _cache[key]
    name = s.llm_provider.lower()
    prov: LLMProvider
    if name == "anthropic" and s.llm_api_key:
        prov = AnthropicProvider(s.llm_api_key, s.llm_model, s.llm_base_url, s.llm_timeout_seconds)
    elif name == "openai" and s.llm_api_key:
        prov = OpenAIProvider(s.llm_api_key, s.llm_model, s.llm_base_url, s.llm_timeout_seconds)
    elif name == "openai_compatible" and s.llm_base_url:
        prov = OpenAIProvider(s.llm_api_key, s.llm_model, s.llm_base_url, s.llm_timeout_seconds, name="openai_compatible")
    else:
        if name not in ("extractive", ""):
            log.warning("LLM_PROVIDER=%s is not usable (missing key/base URL); using local extractive composer", name)
        prov = ExtractiveProvider()
    _cache[key] = prov
    return prov


def provider_status() -> dict:
    p = get_provider()
    return {"provider": p.name, "model": p.model, "is_llm": p.is_llm, "configured": get_settings().llm_provider}
