"""Free fallback summary: sentences several independent groups agree on.

Used for mature stories that have no LLM summary yet (budget exhausted, provider down,
or not yet in the top-K). Sentences are taken verbatim from the outlets' own text, in
each page language, and ranked by how many independence groups have a similar sentence.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cluster import lead_of
from .coverage import Coverage
from .nlp.normalize import clean_display, sentences, tokens

_MIN_TOKENS = 6
_MAX_TOKENS = 60
# Words that mark opinion or rhetoric rather than reporting.
_OPINION = {
    "en": {"shocking", "outrageous", "heroic", "brutal", "disgraceful", "must", "should",
           "we", "our", "i"},
    "fa": {"ننگین", "جنایتکار", "قهرمانانه", "وحشیانه", "باید", "ما", "مزدور"},
}


@dataclass
class ExtractiveSentence:
    text: str
    n_groups: int
    article_ids: list[int]


def _content(toks: list[str]) -> set[str]:
    return {t for t in toks if len(t) > 2}


def extractive_summary(cov: Coverage, lang: str, limit: int = 3,
                       lead_chars: int = 1200) -> list[ExtractiveSentence]:
    cands: list[tuple[str, set[str], str, int]] = []  # text, tokens, group, article id
    for a in cov.articles:
        if a.is_dup or a.lang != lang:
            continue
        body = lead_of(a.title, a.text, a.summary, lead_chars)
        for s in sentences(body)[:6]:
            toks = tokens(s)
            if not (_MIN_TOKENS <= len(toks) <= _MAX_TOKENS):
                continue
            if set(toks) & _OPINION.get(lang, set()) or '"' in s[:2] or "«" in s[:2]:
                continue
            cands.append((clean_display(s), _content(toks), a.group, a.id))
    scored: list[ExtractiveSentence] = []
    for text, toks, group, aid in cands:
        groups, ids = {group}, {aid}
        for _, other, g2, aid2 in cands:
            if g2 == group or not toks or not other:
                continue
            if len(toks & other) / len(toks | other) >= 0.25:
                groups.add(g2)
                ids.add(aid2)
        scored.append(ExtractiveSentence(text, len(groups), sorted(ids)))
    scored.sort(key=lambda s: -s.n_groups)
    out: list[ExtractiveSentence] = []
    used: list[set[str]] = []
    for s in scored:
        toks = _content(tokens(s.text))
        if any(len(toks & u) / max(1, len(toks | u)) >= 0.4 for u in used):
            continue  # near-repeat of a sentence already chosen
        out.append(s)
        used.append(toks)
        if len(out) >= limit:
            break
    return out
