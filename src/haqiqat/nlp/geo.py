"""Place tagging with a small bilingual gazetteer (config/gazetteer.yaml).

Countries and major places are matched on normalized tokens (1-3 word n-grams), so no
model or API is needed. The gazetteer is data: extend it by pull request, or generate a
larger one from GeoNames (CC BY) later.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .normalize import tokens


class RegionDef(BaseModel):
    name: dict[str, str]
    countries: list[str] = Field(default_factory=list)  # empty = everything


class Regions(BaseModel):
    order: list[str]
    regions: dict[str, RegionDef]

    def for_countries(self, countries: set[str]) -> list[str]:
        out = []
        for rid in self.order:
            r = self.regions[rid]
            if not r.countries or countries & set(r.countries):
                out.append(rid)
        return out


def load_regions(path: Path) -> Regions:
    return Regions.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass
class Gazetteer:
    names: dict[tuple[str, ...], str]  # token n-gram -> country code
    max_len: int
    country_names: dict[str, dict[str, str]]  # code -> {lang: display name}

    @classmethod
    def load(cls, path: Path) -> Gazetteer:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        names: dict[tuple[str, ...], str] = {}
        display: dict[str, dict[str, str]] = {}
        for code, entry in data.items():
            display[code] = {lang: vals[0] for lang, vals in entry.items() if vals}
            for vals in entry.values():
                for name in vals:
                    key = tuple(tokens(name))
                    if key:
                        names[key] = code
        max_len = max((len(k) for k in names), default=1)
        return cls(names=names, max_len=max_len, country_names=display)

    def countries(self, text: str) -> Counter:
        toks = tokens(text)
        found: Counter = Counter()
        i = 0
        while i < len(toks):
            matched = False
            for n in range(min(self.max_len, len(toks) - i), 0, -1):
                code = self.names.get(tuple(toks[i : i + n]))
                if code:
                    found[code] += 1
                    i += n
                    matched = True
                    break
            if not matched:
                i += 1
        return found

    def display(self, code: str, lang: str) -> str:
        names = self.country_names.get(code, {})
        return names.get(lang) or names.get("en") or code


def story_countries(per_article: list[Counter], min_share: float = 0.3) -> list[str]:
    """Countries mentioned by at least `min_share` of a story's articles (and at least one).

    Titles and leads name the places a story is about; a single passing mention in one
    article does not make a story "about" that country.
    """
    if not per_article:
        return []
    mentions: Counter = Counter()
    for c in per_article:
        mentions.update(set(c))
    n = len(per_article)
    need = max(1, round(n * min_share))
    ranked = [code for code, k in mentions.most_common() if k >= need]
    return ranked[:6]
