"""Evaluate an embeddings provider on labeled article pairs before trusting it.

Each pair is two headlines-plus-leads that either describe the same event or two
different (often deliberately similar) events. A good multilingual model scores
same-event pairs well above different-event pairs, including English-Persian pairs.
The report suggests the clustering threshold that separates them best.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml

from .embed import Embedder


def evaluate_pairs(embedder: Embedder, pairs_path: Path, current_threshold: float) -> dict:
    pairs = yaml.safe_load(pairs_path.read_text(encoding="utf-8"))["pairs"]
    a = embedder.embed([p["a"] for p in pairs])
    b = embedder.embed([p["b"] for p in pairs])
    sims = (a * b).sum(axis=1)
    same = np.array([bool(p["same"]) for p in pairs])

    def accuracy(th: float) -> float:
        return float(((sims >= th) == same).mean())

    grid = np.round(np.arange(0.30, 0.96, 0.01), 2)
    best = max(grid, key=accuracy)
    by_langs: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"same": [], "diff": []})
    for p, s in zip(pairs, sims, strict=True):
        by_langs[p.get("langs", "?")]["same" if p["same"] else "diff"].append(float(s))
    return {
        "model": embedder.model,
        "pairs": len(pairs),
        "mean_same": round(float(sims[same].mean()), 3) if same.any() else None,
        "mean_different": round(float(sims[~same].mean()), 3) if (~same).any() else None,
        "accuracy_at_current_threshold": round(accuracy(current_threshold), 3),
        "current_threshold": current_threshold,
        "suggested_threshold": float(best),
        "accuracy_at_suggested": round(accuracy(best), 3),
        "by_language_pair": {
            k: {
                "same_mean": round(float(np.mean(v["same"])), 3) if v["same"] else None,
                "different_mean": round(float(np.mean(v["diff"])), 3) if v["diff"] else None,
            }
            for k, v in sorted(by_langs.items())
        },
    }
