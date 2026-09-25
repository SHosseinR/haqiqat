"""Native Claude backend through the official Anthropic SDK (`pip install haqiqat[anthropic]`).

Using the native API instead of an OpenAI-compatible shim gives us prompt caching of the
long, stable system prompt, JSON-schema structured outputs, effort control and
server-side refusal fallbacks.
"""

from __future__ import annotations

from ..config import ProviderConfig
from .base import ChatRequest, ChatResult, ProviderError, api_key, parse_json

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeChat:
    name = "anthropic"

    def __init__(self, cfg: ProviderConfig):
        try:
            import anthropic
        except ImportError as e:
            raise ProviderError(
                "the anthropic provider needs the SDK: pip install 'haqiqat[anthropic]'"
            ) from e
        self._anthropic = anthropic
        self.cfg = cfg
        kwargs: dict = {"timeout": cfg.timeout}
        key = api_key(cfg.api_key_env)
        if key:
            kwargs["api_key"] = key
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        self.client = anthropic.Anthropic(**kwargs)

    def complete_json(self, req: ChatRequest) -> ChatResult:
        output_config: dict = {"format": {"type": "json_schema", "schema": req.schema}}
        if req.effort:
            output_config["effort"] = req.effort
        kwargs: dict = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            # The system prompt is identical for every story, so cache it.
            "system": [
                {"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": [{"role": "user", "content": req.user}],
            "output_config": output_config,
        }
        a = self._anthropic
        try:
            if self.cfg.fallbacks:
                resp = self.client.beta.messages.create(
                    **kwargs, betas=[FALLBACK_BETA], fallbacks=self.cfg.fallbacks
                )
            else:
                resp = self.client.messages.create(**kwargs)
        except a.RateLimitError as e:
            raise ProviderError(f"rate limited: {e.message}") from e
        except a.APIStatusError as e:
            raise ProviderError(f"HTTP {e.status_code}: {e.message}") from e
        except a.APIConnectionError as e:
            raise ProviderError(f"connection error: {e}") from e

        usage = resp.usage
        result = ChatResult(
            data={},
            model=resp.model,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )
        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise ProviderError(f"model declined (refusal, category={category})")
        if resp.stop_reason == "max_tokens":
            raise ProviderError("output truncated (max_tokens); raise max_output_tokens")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        result.data = parse_json(text)
        return result
