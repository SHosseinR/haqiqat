"""When a story gets an LLM summary, and when it gets a new version.

1. A story is summarized for the first time only when it is mature: at least
   `min_groups_for_synthesis` independent groups and among the top-K by score. Stories
   that gain several groups within an hour are fast-tracked.
2. A new version is made only on material change: a new independence group, article
   count grown by `growth_ratio`, or a novel article (far from everything the current
   facts cite). Re-summaries are debounced and capped per day.
3. The caller spends the daily budget on candidates in priority order
   (score x size of change).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from .config import Config
from .coverage import ArticleInfo, Coverage, story_coverage
from .db import from_blob, iso, loads, parse_iso, utcnow
from .sources import Registry

NEW = "new"
FAST_TRACK = "fast_track"
NEW_GROUPS = "new_groups"
GROWTH = "growth"
NOVEL = "novel"


@dataclass
class Candidate:
    story_id: int
    version: int  # the version this would create
    triggers: list[str]
    priority: float
    coverage: Coverage
    new_articles: list[ArticleInfo] = field(default_factory=list)

    @property
    def is_update(self) -> bool:
        return self.version > 1


def _novel(conn: sqlite3.Connection, new_ids: list[int], cited_ids: list[int],
           threshold: float) -> bool:
    if not new_ids or not cited_ids:
        return False

    def vectors(ids: list[int]) -> np.ndarray:
        rows = conn.execute(
            f"SELECT embedding FROM articles WHERE id IN ({','.join('?' * len(ids))})"
            " AND embedding IS NOT NULL", ids,
        ).fetchall()
        return np.stack([from_blob(r["embedding"]) for r in rows]) if rows else np.zeros((0,))

    new_v, cited_v = vectors(new_ids), vectors(cited_ids)
    if new_v.size == 0 or cited_v.size == 0:
        return False
    best = (new_v @ cited_v.T).max(axis=1)
    return bool((best < threshold).any())


def _cited_ids(output: dict) -> list[int]:
    ids: set[int] = set()
    for f in output.get("facts", []):
        ids.update(int(i) for i in f.get("supporting", []))
    return sorted(ids)


def versions_today(conn: sqlite3.Connection, story_id: int, now: datetime) -> int:
    day = now.strftime("%Y-%m-%d")
    return conn.execute(
        "SELECT COUNT(*) FROM syntheses WHERE story_id=? AND substr(created_at,1,10)=?",
        (story_id, day),
    ).fetchone()[0]


def select_candidates(conn: sqlite3.Connection, cfg: Config, registry: Registry,
                      now: datetime | None = None) -> list[Candidate]:
    lc = cfg.lifecycle
    now = now or utcnow()
    since = iso(now - timedelta(hours=cfg.clustering.window_hours))
    rows = conn.execute(
        "SELECT * FROM stories WHERE merged_into IS NULL AND last_article_at >= ?"
        " ORDER BY score DESC LIMIT ?", (since, lc.top_k_candidates),
    ).fetchall()
    out: list[Candidate] = []
    for pos, row in enumerate(rows):
        cov = story_coverage(conn, registry, row["id"])
        if cov.n_groups < lc.min_groups_for_synthesis:
            continue
        score = max(row["score"], 1e-3)
        if row["current_version"] == 0:
            fast = cov.groups_since(now - timedelta(hours=lc.fast_track_hours))
            if fast >= lc.fast_track_groups:
                out.append(Candidate(row["id"], 1, [FAST_TRACK], score * 3, cov))
            else:
                out.append(Candidate(row["id"], 1, [NEW], score * 2, cov))
            continue

        known = set(loads(row["last_synth_article_ids"], []))
        new_articles = [a for a in cov.articles if a.id not in known and not a.is_dup]
        if not new_articles:
            continue
        triggers = []
        new_groups = set(cov.groups) - set(loads(row["last_synth_groups"], []))
        if new_groups:
            triggers.append(NEW_GROUPS)
        growth = len(cov.articles) / max(1, len(known))
        if growth >= lc.growth_ratio:
            triggers.append(GROWTH)
        syn = conn.execute(
            "SELECT output FROM syntheses WHERE story_id=? ORDER BY version DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        cited = _cited_ids(loads(syn["output"], {})) if syn else []
        novel = _novel(conn, [a.id for a in new_articles], cited, lc.novelty_threshold)
        if novel:
            triggers.append(NOVEL)
        if not triggers:
            continue
        debounce = lc.debounce_hours_top if pos < lc.top_n_for_short_debounce \
            else lc.debounce_hours_other
        last = parse_iso(row["last_synth_at"]) if row["last_synth_at"] else None
        if last and now - last < timedelta(hours=debounce):
            continue
        if versions_today(conn, row["id"], now) >= lc.max_versions_per_day:
            continue
        change = len(new_groups) + (growth - 1) + (0.5 if novel else 0)
        out.append(Candidate(
            row["id"], row["current_version"] + 1, triggers, score * (1 + change), cov,
            new_articles=new_articles,
        ))
    out.sort(key=lambda c: c.priority, reverse=True)
    return out
