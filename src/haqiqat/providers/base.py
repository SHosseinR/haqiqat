from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np


class ProviderError(Exception):
    pass


@dataclass
class ChatResult:
    data: dict
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class EmbedResult:
    vectors: np.ndarray
    model: str
    tokens: int = 0


@dataclass
class ChatRequest:
    system: str
    user: str
    schema: dict
    schema_name: str
    model: str
    max_tokens: int
    effort: str | None = None
    # The structured payload the user message was rendered from. Real providers ignore
    # it; the fake provider uses it to produce deterministic, input-grounded output.
    context: dict[str, Any] = field(default_factory=dict)


class ChatProvider(Protocol):
    name: str

    def complete_json(self, req: ChatRequest) -> ChatResult: ...


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, texts: list[str], model: str, dimensions: int | None = None) -> EmbedResult: ...


def api_key(env_name: str | None) -> str | None:
    if not env_name:
        return None
    value = os.environ.get(env_name)
    if not value:
        raise ProviderError(f"environment variable {env_name} is not set")
    return value


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json(text: str) -> dict:
    """Parse model output as JSON, tolerating code fences and leading prose."""
    text = _FENCE.sub("", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise ProviderError("model did not return valid JSON")
