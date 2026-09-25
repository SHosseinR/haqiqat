"""Pluggable model providers. Every pipeline stage names a provider in config.yaml."""

from __future__ import annotations

from ..config import Config, ProviderConfig
from .base import ChatProvider, ChatResult, EmbeddingProvider, EmbedResult, ProviderError

__all__ = [
    "ChatProvider",
    "ChatResult",
    "EmbedResult",
    "EmbeddingProvider",
    "ProviderError",
    "chat_provider",
    "embedding_provider",
]


def _provider_config(cfg: Config, name: str) -> ProviderConfig:
    try:
        return cfg.providers[name]
    except KeyError:
        raise ProviderError(f"provider {name!r} is not defined under `providers:`") from None


def chat_provider(cfg: Config, name: str) -> ChatProvider:
    pc = _provider_config(cfg, name)
    if pc.kind == "openai_compat":
        from .openai_compat import OpenAICompatChat

        return OpenAICompatChat(pc)
    if pc.kind == "anthropic":
        from .claude import ClaudeChat

        return ClaudeChat(pc)
    if pc.kind == "fake":
        from .fake import FakeChat

        return FakeChat()
    raise ProviderError(f"provider {name!r} of kind {pc.kind!r} cannot do chat")


def embedding_provider(cfg: Config, name: str) -> EmbeddingProvider:
    pc = _provider_config(cfg, name)
    if pc.kind == "openai_compat":
        from .openai_compat import OpenAICompatEmbeddings

        return OpenAICompatEmbeddings(pc)
    if pc.kind == "local":
        from .local import LocalEmbeddings

        return LocalEmbeddings()
    if pc.kind == "fake":
        from .fake import FakeEmbeddings

        return FakeEmbeddings()
    raise ProviderError(
        f"provider {name!r} of kind {pc.kind!r} cannot do embeddings "
        "(Anthropic has no embeddings endpoint; use an openai_compat or local provider)"
    )
