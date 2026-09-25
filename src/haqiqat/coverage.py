"""Who covered a story: independence groups, camps and timing.

This is the one place that turns "articles" into "independent confirmations". A
near-duplicate copy inherits the independence group of the article it copies, so
syndication never inflates coverage.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from .db import loads, parse_iso
from .sources import Registry


@dataclass
class ArticleInfo:
    id: int
    source_id: str
    group: str
    camp: str
    lang: str
    title: str
    url: str
    published_at: datetime
    is_dup: bool
    summary: str
    text: str | None


@dataclass
class Coverage:
    articles: list[ArticleInfo]
    countries: set[str]
    groups: dict[str, datetime] = field(default_factory=dict)  # group -> first seen
    group_camp: dict[str, str] = field(default_factory=dict)

    @property
    def n_groups(self) -> int:
        return len(self.groups)

    def camps(self) -> Counter:
        """Number of independence groups per camp."""
        return Counter(self.group_camp.values())

    def groups_since(self, since: datetime) -> int:
        return sum(1 for t in self.groups.values() if t >= since)

    def by_id(self) -> dict[int, ArticleInfo]:
        return {a.id: a for a in self.articles}


def story_coverage(conn: sqlite3.Connection, registry: Registry, story_id: int) -> Coverage:
    story = conn.execute("SELECT countries FROM stories WHERE id=?", (story_id,)).fetchone()
    countries = set(loads(story["countries"], []) if story else [])
    rows = conn.execute(
        "SELECT a.id, a.source_id, a.title, a.url, a.lang, a.published_at, a.dup_of, a.summary,"
        " a.text, r.source_id AS root_source FROM articles a"
        " LEFT JOIN articles r ON r.id = a.dup_of"
        " WHERE a.story_id = ? ORDER BY a.published_at",
        (story_id,),
    ).fetchall()
    cov = Coverage(articles=[], countries=countries)
    for r in rows:
        origin = registry.get(r["root_source"] or r["source_id"])
        src = registry.get(r["source_id"])
        if origin is None or src is None:
            continue  # source removed from registry since ingestion
        group = origin.independence_group
        camp = registry.lenses.camp(origin, countries)
        published = parse_iso(r["published_at"])
        cov.articles.append(ArticleInfo(
            id=r["id"], source_id=r["source_id"], group=group, camp=camp,
            lang=r["lang"] or src.languages[0], title=r["title"], url=r["url"],
            published_at=published, is_dup=r["dup_of"] is not None,
            summary=r["summary"] or "", text=r["text"],
        ))
        if group not in cov.groups or published < cov.groups[group]:
            cov.groups[group] = published
        cov.group_camp.setdefault(group, camp)
    return cov
