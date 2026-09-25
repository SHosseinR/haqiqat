"""OpenAI-compatible HTTP API: OpenAI, Mistral, OpenRouter, DeepSeek, Groq, Together,
self-hosted Ollama or vLLM, and anything else that speaks /chat/completions and /embeddings.
"""

from __future__ import annotations

import httpx
import numpy as np

from ..config import ProviderConfig
from .base import ChatRequest, ChatResult, EmbedResult, ProviderError, api_key, parse_json


class _Client:
    def __init__(self, cfg: ProviderConfig):
        if not cfg.base_url:
            raise ProviderError("openai_compat providers need a base_url")
        self.cfg = cfg
        self.name = "openai_compat"
        headers = {"Content-Type": "application/json"}
        key = api_key(cfg.api_key_env)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self.http = httpx.Client(
            base_url=cfg.base_url.rstrip("/"), headers=headers, timeout=cfg.timeout
        )

    def post(self, path: str, body: dict) -> dict:
        try:
            r = self.http.post(path, json=body)
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.cfg.base_url}{path}: {e}") from e
        if r.status_code >= 400:
            raise ProviderError(f"{self.cfg.base_url}{path}: HTTP {r.status_code}: {r.text[:500]}")
        return r.json()


class OpenAICompatChat(_Client):
    def complete_json(self, req: ChatRequest) -> ChatResult:
        body: dict = {
            "model": req.model,
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.user},
            ],
            self.cfg.max_tokens_field: req.max_tokens,
        }
        if self.cfg.json_mode == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": req.schema_name, "schema": req.schema, "strict": True},
            }
        elif self.cfg.json_mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        data = self.post("/chat/completions", body)
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"unexpected response shape: {str(data)[:300]}") from e
        if choice.get("finish_reason") == "length":
            raise ProviderError("output truncated (finish_reason=length); raise max_output_tokens")
        usage = data.get("usage") or {}
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        return ChatResult(
            data=parse_json(content or ""),
            model=data.get("model", req.model),
            input_tokens=max(0, (usage.get("prompt_tokens") or 0) - cached),
            output_tokens=usage.get("completion_tokens") or 0,
            cache_read_tokens=cached,
        )


class OpenAICompatEmbeddings(_Client):
    def embed(self, texts: list[str], model: str, dimensions: int | None = None) -> EmbedResult:
        body: dict = {"model": model, "input": texts}
        if dimensions:
            body["dimensions"] = dimensions
        data = self.post("/embeddings", body)
        try:
            rows = sorted(data["data"], key=lambda d: d["index"])
            vectors = np.array([r["embedding"] for r in rows], dtype=np.float32)
        except (KeyError, TypeError) as e:
            raise ProviderError(f"unexpected embeddings response: {str(data)[:300]}") from e
        if len(vectors) != len(texts):
            raise ProviderError(f"asked for {len(texts)} embeddings, got {len(vectors)}")
        usage = data.get("usage") or {}
        tokens = usage.get("prompt_tokens") or usage.get("total_tokens") or 0
        return EmbedResult(vectors=vectors, model=model, tokens=tokens)
