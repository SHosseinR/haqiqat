"""Embedding with a content-hash cache and spend recording.

Identical text (syndicated copies, re-fetched articles, taxonomy descriptions) is embedded
once per model. Every vector is L2-normalized, so cosine similarity is a dot product.
"""

from __future__ import annotations

import hashlib
import sqlite3

import numpy as np

from .budget import Budget, cost_usd
from .config import Config
from .db import from_blob, to_blob
from .providers import embedding_provider


def embedding_text(title: str, lead: str | None, max_chars: int) -> str:
    text = title.strip()
    if lead:
        text = f"{text}\n{lead.strip()}"
    return text[:max_chars]


class Embedder:
    def __init__(self, conn: sqlite3.Connection, cfg: Config, budget: Budget | None = None):
        self.conn = conn
        self.cfg = cfg
        self.ec = cfg.embeddings
        self.model = self.ec.model
        self.provider = embedding_provider(cfg, self.ec.provider)
        self.budget = budget or Budget(conn, cfg)

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        hashes = [self._hash(t) for t in texts]
        cached: dict[str, np.ndarray] = {}
        for i in range(0, len(hashes), 500):
            chunk = hashes[i : i + 500]
            rows = self.conn.execute(
                f"SELECT hash, vector FROM embedding_cache WHERE model = ? AND hash IN "
                f"({','.join('?' * len(chunk))})",
                [self.model, *chunk],
            ).fetchall()
            cached.update({r["hash"]: from_blob(r["vector"]) for r in rows})

        missing = [(h, t) for h, t in zip(hashes, texts, strict=True) if h not in cached]
        # Deduplicate within the batch too.
        todo = list(dict(missing).items())
        bs = self.ec.batch_size
        for i in range(0, len(todo), bs):
            batch = todo[i : i + bs]
            try:
                res = self.provider.embed(
                    [t for _, t in batch], self.model, dimensions=self.ec.dimensions
                )
            except Exception as e:
                self.budget.record(stage="embed", provider=self.ec.provider, model=self.model,
                                   ok=False, error=str(e)[:500])
                raise
            vecs = res.vectors
            norms = np.linalg.norm(vecs, axis=1, keepdims=True).clip(1e-9)
            vecs = (vecs / norms).astype(np.float32)
            self.conn.executemany(
                "INSERT OR REPLACE INTO embedding_cache (hash, model, vector) VALUES (?,?,?)",
                [(h, self.model, to_blob(v)) for (h, _), v in zip(batch, vecs, strict=True)],
            )
            for (h, _), v in zip(batch, vecs, strict=True):
                cached[h] = v
            self.budget.record(
                stage="embed", provider=self.ec.provider, model=self.model,
                input_tokens=res.tokens,
                cost=cost_usd(self.cfg, self.model, input_tokens=res.tokens),
            )
        self.conn.commit()
        return np.stack([cached[h] for h in hashes])
