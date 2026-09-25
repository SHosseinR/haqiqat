"""Source registry: one YAML file per outlet under sources/, plus lens definitions.

The registry is data, not code: anyone can propose a new outlet or a rating change by
pull request, and every label must cite evidence (see docs/source-rating.md).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

SourceType = Literal[
    "news_agency",
    "newspaper",
    "broadcaster",
    "online",
    "wire",
    "monitor",
    "government",
    "intergovernmental",
]
OwnershipKind = Literal["state", "public", "private", "nonprofit", "party", "unknown"]
ReliabilityRating = Literal[
    "unreviewed",
    "generally_reliable",
    "no_consensus",
    "generally_unreliable",
    "deprecated",
    "not_listed",
]


def _web_url(v: str) -> str:
    if not re.match(r"^https?://[^\s/]+", v):
        raise ValueError(f"must be an http(s) URL, got {v!r}")
    return v


class Localized(BaseModel):
    en: str
    fa: str | None = None

    def get(self, lang: str) -> str:
        return getattr(self, lang, None) or self.en


class Evidence(BaseModel):
    url: str
    note: str | None = None

    _check_url = field_validator("url")(classmethod(lambda cls, v: _web_url(v)))


class Feed(BaseModel):
    url: str
    kind: Literal["rss", "sitemap"] = "rss"
    language: str | None = None  # overrides the source's first language
    enabled: bool = True
    # Set to true by a maintainer after `haqiqat validate-sources --probe` succeeds.
    verified: bool = False
    note: str | None = None

    _check_url = field_validator("url")(classmethod(lambda cls, v: _web_url(v)))


class Ownership(BaseModel):
    kind: OwnershipKind
    state: str | None = None  # ISO 3166 code of the state that owns or funds it, if any
    owner: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class Reliability(BaseModel):
    # "unreviewed" until a maintainer has checked the current Wikipedia page.
    wikipedia_en: ReliabilityRating = "unreviewed"
    wikipedia_fa: ReliabilityRating = "unreviewed"
    state_media_monitor: str | None = None
    notes: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class Source(BaseModel):
    id: str
    name: Localized
    homepage: str
    languages: list[str]
    country: str  # ISO 3166 code where it is based
    type: SourceType
    ownership: Ownership
    # Outlets under common ownership or control share a group; corroboration counts
    # groups, not outlets.
    independence_group: str
    # axis id -> position id, validated against config/lenses.yaml
    lenses: dict[str, str]
    reliability: Reliability = Reliability()
    focus_regions: list[str] = Field(default_factory=list)
    feeds: list[Feed] = Field(default_factory=list)
    enabled: bool = True
    notes: str | None = None

    _check_homepage = field_validator("homepage")(classmethod(lambda cls, v: _web_url(v)))

    @field_validator("id", "independence_group")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", v):
            raise ValueError(f"must be a lowercase slug, got {v!r}")
        return v

    def feed_language(self, feed: Feed) -> str:
        return feed.language or self.languages[0]


class LensPosition(BaseModel):
    name: Localized
    camp: str
    description: Localized | None = None


class LensAxis(BaseModel):
    name: Localized
    description: Localized | None = None
    # The axis is the primary lens for stories involving any of these countries.
    # Empty means it is the fallback axis used for every story.
    primary_for_countries: list[str] = Field(default_factory=list)
    camps: dict[str, Localized]
    positions: dict[str, LensPosition]


class Lenses(BaseModel):
    fallback_axis: str
    axes: dict[str, LensAxis]

    def primary_axis(self, story_countries: set[str]) -> str:
        for axis_id, axis in self.axes.items():
            if story_countries & set(axis.primary_for_countries):
                return axis_id
        return self.fallback_axis

    def camp(self, source: Source, story_countries: set[str]) -> str:
        """Camp of a source for a given story: its position on the story's primary axis,
        falling back to the fallback axis when the source has no position on it."""
        axis_id = self.primary_axis(story_countries)
        for aid in (axis_id, self.fallback_axis):
            pos = source.lenses.get(aid)
            if pos is not None:
                return f"{aid}:{self.axes[aid].positions[pos].camp}"
        return "unknown"

    def camp_name(self, camp: str, lang: str) -> str:
        if ":" not in camp:
            return camp
        axis_id, camp_id = camp.split(":", 1)
        axis = self.axes.get(axis_id)
        if axis is None or camp_id not in axis.camps:
            return camp_id
        return axis.camps[camp_id].get(lang)

    def position_name(self, axis_id: str, pos: str, lang: str) -> str:
        axis = self.axes.get(axis_id)
        if axis is None or pos not in axis.positions:
            return pos
        return axis.positions[pos].name.get(lang)


class Registry(BaseModel):
    sources: dict[str, Source]
    lenses: Lenses

    def get(self, source_id: str) -> Source | None:
        return self.sources.get(source_id)

    def enabled(self) -> list[Source]:
        return [s for s in self.sources.values() if s.enabled]


class RegistryError(Exception):
    pass


def load_lenses(path: Path) -> Lenses:
    return Lenses.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_registry(sources_dir: Path, lenses_path: Path) -> Registry:
    lenses = load_lenses(lenses_path)
    sources: dict[str, Source] = {}
    errors: list[str] = []
    for f in sorted(sources_dir.rglob("*.yaml")):
        try:
            src = Source.model_validate(yaml.safe_load(f.read_text(encoding="utf-8")))
        except Exception as e:
            errors.append(f"{f}: {e}")
            continue
        if src.id in sources:
            errors.append(f"{f}: duplicate source id {src.id!r}")
            continue
        if f.stem != src.id:
            errors.append(f"{f}: file name must match id {src.id!r}")
        for axis_id, pos in src.lenses.items():
            axis = lenses.axes.get(axis_id)
            if axis is None:
                errors.append(f"{f}: unknown lens axis {axis_id!r}")
            elif pos not in axis.positions:
                errors.append(f"{f}: unknown position {pos!r} on axis {axis_id!r}")
        if lenses.fallback_axis not in src.lenses:
            errors.append(f"{f}: every source needs a position on {lenses.fallback_axis!r}")
        sources[src.id] = src
    if errors:
        raise RegistryError("\n".join(errors))
    return Registry(sources=sources, lenses=lenses)


def source_json_schema() -> dict:
    schema = Source.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Haqiqat source"
    return schema
