"""Read models for publishing: everything a page or a Telegram post shows about a story."""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import Config
from .coverage import ArticleInfo, Coverage, story_coverage
from .db import iso, loads, parse_iso, utcnow
from .extractive import ExtractiveSentence, extractive_summary
from .labels import LabeledFact, blindspot, label_facts
from .nlp.normalize import clean_display
from .sources import Registry

LLM = "llm"
EXTRACTIVE = "extractive"
HEADLINES = "headlines"


@dataclass
class ArticleView:
    id: int
    title: str
    url: str
    source_id: str
    source_name: dict[str, str]
    camp: str
    lang: str
    published_at: datetime
    is_dup: bool


@dataclass
class SynthMeta:
    version: int
    created_at: datetime
    provider: str
    model: str
    prompt_version: str
    cost_usd: float
    input_article_ids: list[int]
    triggers: list[str]
    style_flags: list[str]


@dataclass
class StoryView:
    id: int
    score: float
    score_parts: dict
    first_article_at: datetime
    last_article_at: datetime
    countries: list[str]
    regions: list[str]
    category: str | None
    storyline_id: int | None
    kind: str
    title: dict[str, str]
    title_source: dict[str, str]  # for headline fallback: which outlet's headline
    summary: dict[str, str]
    facts: list[LabeledFact]
    disputes: list[dict]
    extractive: dict[str, list[ExtractiveSentence]]
    synth: SynthMeta | None
    n_groups: int
    camps: Counter
    blindspot: str | None
    articles: list[ArticleView]
    new_since_summary: list[ArticleView] = field(default_factory=list)

    def article(self, aid: int) -> ArticleView | None:
        for a in self.articles:
            if a.id == aid:
                return a
        return None


def _article_view(a: ArticleInfo, registry: Registry) -> ArticleView:
    src = registry.get(a.source_id)
    name = {"en": src.name.en, "fa": src.name.get("fa")} if src else {"en": a.source_id,
                                                                        "fa": a.source_id}
    return ArticleView(
        id=a.id, title=clean_display(a.title), url=a.url, source_id=a.source_id,
        source_name=name, camp=a.camp, lang=a.lang, published_at=a.published_at,
        is_dup=a.is_dup,
    )


def _headline(cov: Coverage, lang: str, registry: Registry) -> tuple[str, str]:
    originals = [a for a in cov.articles if not a.is_dup]
    pool = [a for a in originals if a.lang == lang] or originals or cov.articles
    a = pool[0]
    src = registry.get(a.source_id)
    return clean_display(a.title), (src.name.get(lang) if src else a.source_id)


def build_story(conn: sqlite3.Connection, cfg: Config, registry: Registry,
                row: sqlite3.Row) -> StoryView:
    cov = story_coverage(conn, registry, row["id"])
    syn = conn.execute(
        "SELECT * FROM syntheses WHERE story_id=? ORDER BY version DESC LIMIT 1", (row["id"],)
    ).fetchone()
    langs = cfg.site.languages
    articles = [_article_view(a, registry) for a in cov.articles]
    title, title_source, summary = {}, {}, {}
    facts: list[LabeledFact] = []
    disputes: list[dict] = []
    extractive: dict[str, list[ExtractiveSentence]] = {}
    meta = None
    new_since: list[ArticleView] = []
    if syn:
        out = loads(syn["output"])
        kind = LLM
        for lang in langs:
            title[lang] = out["title"].get(lang) or out["title"]["en"]
            summary[lang] = out["summary"].get(lang) or out["summary"]["en"]
            title_source[lang] = ""
        facts = label_facts(out.get("facts", []), cov, cfg.labels)
        disputes = out.get("disputes", [])
        meta = SynthMeta(
            version=syn["version"], created_at=parse_iso(syn["created_at"]),
            provider=syn["provider"], model=syn["model"], prompt_version=syn["prompt_version"],
            cost_usd=syn["cost_usd"], input_article_ids=loads(syn["input_article_ids"], []),
            triggers=(syn["trigger"] or "").split(","),
            style_flags=out.get("style_flags", []),
        )
        known = set(loads(row["last_synth_article_ids"], []))
        new_since = [a for a in articles if a.id not in known]
    else:
        for lang in langs:
            extractive[lang] = extractive_summary(cov, lang, lead_chars=cfg.lifecycle.lead_chars)
            title[lang], title_source[lang] = _headline(cov, lang, registry)
            summary[lang] = ""
        kind = EXTRACTIVE if any(extractive.values()) else HEADLINES
    return StoryView(
        id=row["id"], score=row["score"], score_parts=loads(row["score_parts"], {}),
        first_article_at=parse_iso(row["first_article_at"]),
        last_article_at=parse_iso(row["last_article_at"]),
        countries=loads(row["countries"], []), regions=loads(row["regions"], []),
        category=row["category"], storyline_id=row["storyline_id"], kind=kind,
        title=title, title_source=title_source, summary=summary, facts=facts,
        disputes=disputes, extractive=extractive, synth=meta, n_groups=cov.n_groups,
        camps=cov.camps(), blindspot=blindspot(cov, cfg.labels), articles=articles,
        new_since_summary=new_since,
    )


def top_stories(conn: sqlite3.Connection, cfg: Config, registry: Registry, *,
                min_groups: int = 2, limit: int = 200, hours: float | None = None,
                now: datetime | None = None) -> list[StoryView]:
    now = now or utcnow()
    hours = hours or cfg.clustering.window_hours
    rows = conn.execute(
        "SELECT * FROM stories WHERE merged_into IS NULL AND last_article_at >= ?"
        " ORDER BY score DESC", (iso(now - timedelta(hours=hours)),),
    ).fetchall()
    out = []
    for row in rows:
        parts = loads(row["score_parts"], {})
        if parts.get("n_groups", 0) < min_groups:
            continue
        out.append(build_story(conn, cfg, registry, row))
        if len(out) >= limit:
            break
    return out


def storyline_stories(conn: sqlite3.Connection, cfg: Config, registry: Registry,
                      storyline_id: int) -> list[StoryView]:
    rows = conn.execute(
        "SELECT * FROM stories WHERE storyline_id=? AND merged_into IS NULL"
        " ORDER BY first_article_at", (storyline_id,),
    ).fetchall()
    return [build_story(conn, cfg, registry, r) for r in rows]
