"""Offline providers for tests and dry runs. No network, no keys, deterministic output."""

from __future__ import annotations

import hashlib

import numpy as np

from ..nlp.normalize import tokens
from .base import ChatRequest, ChatResult, EmbedResult

# A tiny bilingual lexicon so tests can exercise cross-lingual clustering without a real
# multilingual model. Real providers learn this; the fake one is told.
LEXICON = {
    "ایران": "iran",
    "تهران": "tehran",
    "اسرائیل": "israel",
    "اسراییل": "israel",
    "آمریکا": "us",
    "امریکا": "us",
    "حمله": "attack",
    "پهپاد": "drone",
    "پهپادی": "drone",
    "زلزله": "earthquake",
    "مذاکرات": "talks",
    "هسته‌ای": "nuclear",
    "هستهای": "nuclear",
    "هسته ای": "nuclear",
    "وین": "vienna",
    "کشته": "killed",
    "اصفهان": "isfahan",
    "انتخابات": "election",
    "نفت": "oil",
    "قیمت": "price",
    "تحریم": "sanctions",
    "تحریم‌ها": "sanctions",
    "تحریمها": "sanctions",
    "بازداشت": "arrest",
    "خبرنگار": "journalist",
}
_STOP = {
    "the", "a", "an", "of", "in", "on", "to", "and", "for", "with", "at", "by", "is", "was",
    "were", "are", "as", "from", "after", "new", "says", "said",
    "در", "و", "به", "از", "که", "با", "را", "این", "برای", "است", "شد", "پس",
}
DIM = 256


def _bucket(tok: str) -> int:
    return int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=4).digest(), "little") % DIM


class FakeEmbeddings:
    name = "fake"

    def embed(self, texts: list[str], model: str, dimensions: int | None = None) -> EmbedResult:
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            for tok in tokens(text):
                tok = LEXICON.get(tok, tok)
                if tok in _STOP or len(tok) < 2:
                    continue
                out[i, _bucket(tok)] += 1.0
            n = np.linalg.norm(out[i])
            if n:
                out[i] /= n
        return EmbedResult(vectors=out, model=model, tokens=0)


class FakeChat:
    """Builds a schema-valid synthesis straight from the input articles."""

    name = "fake"

    def complete_json(self, req: ChatRequest) -> ChatResult:
        ctx = req.context
        arts = ctx.get("articles", [])
        refs = [a["ref"] for a in arts]
        first = arts[0] if arts else {"title": "", "lead": "", "source": "", "ref": "A1"}
        facts = []
        if ctx.get("mode") == "update":
            for f in ctx.get("previous", {}).get("facts", []):
                facts.append(
                    {
                        "id": f["id"],
                        "text": f["text"],
                        "kind": f.get("kind", "event"),
                        "attributed_to": f.get("attributed_to") or "",
                        "supporting": refs,
                        "contradicting": [],
                    }
                )
        else:
            facts.append(
                {
                    "id": "F1",
                    "text": {"en": first["title"], "fa": first["title"]},
                    "kind": "event",
                    "attributed_to": "",
                    "supporting": refs,
                    "contradicting": [],
                }
            )
            facts.append(
                {
                    "id": "F2",
                    "text": {
                        "en": f"{first['source']} reported details not yet confirmed elsewhere.",
                        "fa": f"{first['source']} جزئیاتی گزارش کرد که هنوز جای دیگری تأیید نشده.",
                    },
                    "kind": "claim",
                    "attributed_to": first["source"],
                    "supporting": refs[:1],
                    "contradicting": [],
                }
            )
        data = {
            "title": {"en": first["title"][:120], "fa": first["title"][:120]},
            "summary": {
                "en": first.get("lead", "")[:300] or first["title"],
                "fa": first.get("lead", "")[:300] or first["title"],
            },
            "facts": facts,
            "disputes": [],
            "impact": min(10, 2 + len(arts)),
        }
        user_tokens = len(req.user) // 3
        return ChatResult(
            data=data, model="fake-llm", input_tokens=user_tokens, output_tokens=400
        )
