"""Local embeddings with sentence-transformers (`pip install haqiqat[local]`).

For operators with enough RAM (bge-m3 needs roughly 2-3 GB). The default setup uses an
embeddings API instead, which is cheaper than a bigger server at our volume.
"""

from __future__ import annotations

from .base import EmbedResult, ProviderError


class LocalEmbeddings:
    name = "local"

    def __init__(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ProviderError(
                "local embeddings need: pip install 'haqiqat[local]'"
            ) from e
        self._cls = SentenceTransformer
        self._models: dict = {}

    def embed(self, texts: list[str], model: str, dimensions: int | None = None) -> EmbedResult:
        if model not in self._models:
            self._models[model] = self._cls(model)
        vecs = self._models[model].encode(texts, normalize_embeddings=True)
        return EmbedResult(vectors=vecs.astype("float32"), model=model, tokens=0)
