"""LLM provider abstraction. Providers receive a GenerationRequest and return JSON text in the grounded-answer schema."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.schemas.evidence import Evidence


@dataclass
class GenerationRequest:
    question: str
    evidence: list[Evidence]
    entities: list[dict]
    graph_context: list[str]
    system_prompt: str
    user_prompt: str
    intents: list[str] = field(default_factory=list)
    max_tokens: int = 2000


@dataclass
class LLMResult:
    text: str  # JSON per the grounded schema
    provider: str
    model: str
    model_version: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def generate(self, req: GenerationRequest) -> LLMResult: ...

    @property
    def is_llm(self) -> bool:
        return True
