"""Significance ranking: a published formula, recomputed from scratch every run.

    score = (w_groups * log2(1 + independent_groups)
             + w_lens_diversity * lens_diversity
             + w_geo_scope * geo_scope
             + w_velocity * velocity
             + w_impact * llm_impact
             + w_confirmation * confirmation) * recency_decay

No clicks, shares or any engagement signal are used, ever. Weights live in config.yaml.
Ranking never waits for the LLM: impact and confirmation are simply 0 until a story has
a synthesis.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta

from .config import Config
from .coverage import Coverage, story_coverage
from .db import dumps, iso, loads, parse_iso, utcnow
from .labels import confirmation_share, label_facts
from .sources import Registry


def latest_synthesis(conn: sqlite3.Connection, story_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM syntheses WHERE story_id=? ORDER BY version DESC LIMIT 1", (story_id,)
    ).fetchone()


def score_parts(cfg: Config, cov: Coverage, synth: dict | None, last_article_at: datetime,
                now: datetime) -> dict[str, float]:
    rc = cfg.ranking
    camps = cov.camps()
    parts = {
        "groups": math.log2(1 + cov.n_groups),
        "lens_diversity": min(1.0, max(0, len(camps) - 1) / 2),
        "geo_scope": min(1.0, math.log2(1 + len(cov.countries)) / 2.5),
        "velocity": min(1.0, cov.groups_since(now - timedelta(hours=rc.velocity_window_hours)) / 5),
        "impact": 0.0,
        "confirmation": 0.0,
    }
    if synth:
        parts["impact"] = max(0, min(10, int(synth.get("impact", 0)))) / 10
        parts["confirmation"] = confirmation_share(
            label_facts(synth.get("facts", []), cov, cfg.labels)
        )
    age_h = max(0.0, (now - last_article_at).total_seconds() / 3600)
    parts["decay"] = 0.5 ** (age_h / rc.half_life_hours)
    return parts


def total(cfg: Config, parts: dict[str, float]) -> float:
    w = cfg.ranking.weights
    raw = (
        w.groups * parts["groups"]
        + w.lens_diversity * parts["lens_diversity"]
        + w.geo_scope * parts["geo_scope"]
        + w.velocity * parts["velocity"]
        + w.impact * parts["impact"]
        + w.confirmation * parts["confirmation"]
    )
    return round(raw * parts["decay"], 4)


def rank_stories(conn: sqlite3.Connection, cfg: Config, registry: Registry,
                 now: datetime | None = None) -> int:
    now = now or utcnow()
    since = iso(now - timedelta(hours=cfg.clustering.window_hours * 2))
    rows = conn.execute(
        "SELECT id, last_article_at FROM stories WHERE merged_into IS NULL"
        " AND last_article_at >= ?", (since,),
    ).fetchall()
    for r in rows:
        cov = story_coverage(conn, registry, r["id"])
        syn = latest_synthesis(conn, r["id"])
        synth = loads(syn["output"]) if syn and syn["provider"] != "extractive" else None
        parts = score_parts(cfg, cov, synth, parse_iso(r["last_article_at"]), now)
        parts["n_groups"] = cov.n_groups
        conn.execute(
            "UPDATE stories SET score=?, score_parts=? WHERE id=?",
            (total(cfg, parts), dumps({k: round(v, 4) for k, v in parts.items()}), r["id"]),
        )
    conn.commit()
    return len(rows)
