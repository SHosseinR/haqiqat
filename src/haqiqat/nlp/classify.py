"""Zero-shot topic classification against IPTC Media Topics, with no LLM.

Each category's bilingual description is embedded once (cached like any other text);
a story's category is the closest description to its centroid. Once enough LLM-labelled
examples exist, a small trained classifier can replace this (see docs/roadmap.md).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml
from pydantic import BaseModel


class Topic(BaseModel):
    id: str
    name: dict[str, str]
    description: str


class Taxonomy(BaseModel):
    source: str
    topics: list[Topic]

    def name(self, topic_id: str | None, lang: str) -> str:
        for t in self.topics:
            if t.id == topic_id:
                return t.name.get(lang) or t.name["en"]
        return ""


def load_taxonomy(path: Path) -> Taxonomy:
    return Taxonomy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class TopicClassifier:
    def __init__(self, taxonomy: Taxonomy, vectors: np.ndarray):
        self.taxonomy = taxonomy
        self.vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True).clip(1e-9)

    def classify(self, vec: np.ndarray) -> tuple[str, float]:
        v = vec / max(np.linalg.norm(vec), 1e-9)
        sims = self.vectors @ v
        i = int(np.argmax(sims))
        return self.taxonomy.topics[i].id, float(sims[i])
