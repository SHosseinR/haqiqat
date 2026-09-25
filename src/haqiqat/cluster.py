"""Processing new articles: dedup, embed, geo-tag, cluster into stories and storylines.

Hierarchy: article -> story (one event) -> storyline (an ongoing thread) -> category.
Clustering is online: each new article joins the most similar active story or starts a
new one. Everything here is free (no LLM); only the embeddings call an API.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta

import numpy as np

from .config import Config
from .db import dumps, from_blob, iso, loads, parse_iso, to_blob, utcnow
from .embed import Embedder, embedding_text
from .nlp import dedup
from .nlp.classify import TopicClassifier
from .nlp.geo import Gazetteer, Regions, story_countries
from .nlp.lang import detect
from .nlp.normalize import normalize, tokens
from .sources import Registry

log = logging.getLogger(__name__)

MIN_TOKENS_FOR_DEDUP = 25


@dataclass
class ProcessStats:
    processed: int = 0
    duplicates: int = 0
    joined: int = 0
    new_stories: int = 0
    merged: int = 0
    storylines_linked: int = 0


def lead_of(title: str, text: str | None, summary: str | None, chars: int) -> str:
    body = (text or "").strip() or (summary or "").strip()
    if body.startswith(title):
        body = body[len(title):].strip()
    return body[:chars]


def _compatible(a: set[str], b: set[str]) -> bool:
    """Two place sets are compatible unless both are known and disjoint."""
    return not a or not b or bool(a & b)


class Clusterer:
    def __init__(self, conn: sqlite3.Connection, cfg: Config, registry: Registry,
                 embedder: Embedder, gazetteer: Gazetteer, regions: Regions,
                 classifier: TopicClassifier | None = None):
        self.conn = conn
        self.cfg = cfg
        self.cc = cfg.clustering
        self.registry = registry
        self.embedder = embedder
        self.gaz = gazetteer
        self.regions = regions
        self.classifier = classifier

    # --- dedup -----------------------------------------------------------------------
    def _dedup(self, rows: list[sqlite3.Row], stats: ProcessStats) -> list[sqlite3.Row]:
        now = utcnow()
        since = iso(now - timedelta(hours=self.cc.window_hours))
        existing = self.conn.execute(
            "SELECT id, minhash, dup_of FROM articles WHERE processed=1 AND minhash IS NOT NULL"
            " AND published_at >= ?", (since,),
        ).fetchall()
        ids = [r["id"] for r in existing]
        roots = [r["dup_of"] or r["id"] for r in existing]
        sigs = [dedup.from_blob(r["minhash"]) for r in existing]
        keep = []
        for r in rows:
            body = f"{r['title']} {r['text'] or r['summary'] or ''}"[:4000]
            sig = dedup.signature(body)
            enough = len(tokens(body)) >= MIN_TOKENS_FOR_DEDUP
            dup_root = None
            if enough and sigs:
                i, sim = dedup.best_match(sig, np.stack(sigs))
                if sim >= self.cc.near_duplicate_jaccard:
                    dup_root = roots[i]
            self.conn.execute(
                "UPDATE articles SET minhash=? WHERE id=?", (dedup.to_blob(sig), r["id"])
            )
            if dup_root is not None:
                # The copy joins its original's story; if the original arrived in this
                # same batch it has no story yet, and _attach_duplicates fixes that up.
                stats.duplicates += 1
                self.conn.execute(
                    "UPDATE articles SET dup_of=?, processed=1,"
                    " story_id=(SELECT story_id FROM articles WHERE id=?) WHERE id=?",
                    (dup_root, dup_root, r["id"]),
                )
            else:
                keep.append(r)
            if enough:
                ids.append(r["id"])
                roots.append(dup_root or r["id"])
                sigs.append(sig)
        return keep

    # --- stories ---------------------------------------------------------------------
    def _attach_duplicates(self, article_ids: list[int]) -> set[int]:
        self.conn.execute(
            "UPDATE articles SET story_id = (SELECT r.story_id FROM articles r"
            " WHERE r.id = articles.dup_of) WHERE dup_of IS NOT NULL AND story_id IS NULL"
        )
        marks = ",".join("?" * len(article_ids))
        return {
            r["story_id"] for r in self.conn.execute(
                f"SELECT story_id FROM articles WHERE id IN ({marks})"
                " AND dup_of IS NOT NULL AND story_id IS NOT NULL",
                article_ids,
            )
        }

    def _refresh_counts(self, story_ids: set[int]) -> None:
        for sid in story_ids:
            self.conn.execute(
                "UPDATE stories SET n_articles=(SELECT COUNT(*) FROM articles WHERE story_id=?),"
                " first_article_at=COALESCE((SELECT MIN(published_at) FROM articles"
                " WHERE story_id=?), first_article_at),"
                " last_article_at=COALESCE((SELECT MAX(published_at) FROM articles"
                " WHERE story_id=?), last_article_at), updated_at=? WHERE id=?",
                (sid, sid, sid, iso(utcnow()), sid),
            )

    def _active_stories(self):
        since = iso(utcnow() - timedelta(hours=self.cc.window_hours))
        rows = self.conn.execute(
            "SELECT id, centroid, n_articles, countries, last_article_at FROM stories"
            " WHERE merged_into IS NULL AND last_article_at >= ? AND embedding_model = ?",
            (since, self.embedder.model),
        ).fetchall()
        return rows

    def _cluster(self, rows: list[sqlite3.Row], vecs: np.ndarray, stats: ProcessStats
                 ) -> set[int]:
        active = self._active_stories()
        story_ids = [r["id"] for r in active]
        cents = [from_blob(r["centroid"]).copy() for r in active]
        counts = [r["n_articles"] for r in active]
        places = [set(loads(r["countries"], [])) for r in active]
        touched: set[int] = set()
        window = timedelta(hours=self.cc.window_hours)
        last_seen = [parse_iso(r["last_article_at"]) for r in active]

        for row, v in zip(rows, vecs, strict=True):
            art_places = set(loads(row["countries"], {}) or {})
            published = parse_iso(row["published_at"])
            best, best_sim = -1, -1.0
            if cents:
                sims = np.stack(cents) @ v
                for j in np.argsort(-sims):
                    s = float(sims[j])
                    if s < self.cc.join_threshold:
                        break
                    if abs(published - last_seen[j]) > window:
                        continue
                    if s >= self.cc.strong_threshold or _compatible(art_places, places[j]):
                        best, best_sim = int(j), s
                        break
            if best >= 0:
                sid = story_ids[best]
                n = counts[best]
                c = cents[best] * n + v
                cents[best] = c / max(np.linalg.norm(c), 1e-9)
                counts[best] = n + 1
                places[best] |= art_places
                last_seen[best] = max(last_seen[best], published)
                self.conn.execute(
                    "UPDATE stories SET centroid=?, n_articles=?,"
                    " last_article_at=MAX(last_article_at, ?) WHERE id=?",
                    (to_blob(cents[best]), counts[best], row["published_at"], sid),
                )
                stats.joined += 1
                log.debug("article %s joins story %s (%.3f)", row["id"], sid, best_sim)
            else:
                now = iso(utcnow())
                cur = self.conn.execute(
                    "INSERT INTO stories (created_at, updated_at, first_article_at,"
                    " last_article_at, centroid, embedding_model, n_articles, countries)"
                    " VALUES (?,?,?,?,?,?,1,?)",
                    (now, now, row["published_at"], row["published_at"], to_blob(v),
                     self.embedder.model, dumps(sorted(art_places))),
                )
                sid = cur.lastrowid
                story_ids.append(sid)
                cents.append(v.copy())
                counts.append(1)
                places.append(set(art_places))
                last_seen.append(published)
                stats.new_stories += 1
            self.conn.execute(
                "UPDATE articles SET story_id=?, processed=1 WHERE id=?", (sid, row["id"])
            )
            touched.add(sid)
        return touched

    def _merge(self, touched: set[int], stats: ProcessStats) -> set[int]:
        """Merge stories that converged onto the same event as articles accumulated."""
        active = self._active_stories()
        if len(active) < 2:
            return touched
        ids = [r["id"] for r in active]
        idx = {sid: i for i, sid in enumerate(ids)}
        cents = np.stack([from_blob(r["centroid"]) for r in active])
        places = [set(loads(r["countries"], [])) for r in active]
        sizes = [r["n_articles"] for r in active]
        gone: set[int] = set()
        merged_to: dict[int, int] = {}
        for sid in sorted(touched):
            if sid not in idx or sid in gone:
                continue
            i = idx[sid]
            sims = cents @ cents[i]
            for j in np.argsort(-sims):
                j = int(j)
                if j == i or ids[j] in gone:
                    continue
                if sims[j] < self.cc.merge_threshold:
                    break
                if not _compatible(places[i], places[j]):
                    continue
                keep, drop = (i, j) if sizes[i] >= sizes[j] else (j, i)
                self._merge_pair(ids[keep], ids[drop])
                gone.add(ids[drop])
                merged_to[ids[drop]] = ids[keep]
                stats.merged += 1
                c = cents[keep] * sizes[keep] + cents[drop] * sizes[drop]
                cents[keep] = c / max(np.linalg.norm(c), 1e-9)
                sizes[keep] += sizes[drop]
                places[keep] |= places[drop]
                if drop == i:
                    break
        def survivor(s: int) -> int:
            while s in merged_to:
                s = merged_to[s]
            return s

        return {survivor(s) for s in touched}

    def _merge_pair(self, keep: int, drop: int) -> None:
        self.conn.execute("UPDATE articles SET story_id=? WHERE story_id=?", (keep, drop))
        k = self.conn.execute("SELECT * FROM stories WHERE id=?", (keep,)).fetchone()
        d = self.conn.execute("SELECT * FROM stories WHERE id=?", (drop,)).fetchone()
        c = from_blob(k["centroid"]) * k["n_articles"] + from_blob(d["centroid"]) * d["n_articles"]
        c = c / max(np.linalg.norm(c), 1e-9)
        self.conn.execute(
            "UPDATE stories SET centroid=?, n_articles=?,"
            " first_article_at=MIN(first_article_at, ?),"
            " last_article_at=MAX(last_article_at, ?), updated_at=? WHERE id=?",
            (to_blob(c), k["n_articles"] + d["n_articles"], d["first_article_at"],
             d["last_article_at"], iso(utcnow()), keep),
        )
        self.conn.execute("UPDATE stories SET merged_into=? WHERE id=?", (keep, drop))

    # --- attributes ------------------------------------------------------------------
    def _attributes(self, story_ids: set[int]) -> None:
        for sid in story_ids:
            rows = self.conn.execute(
                "SELECT countries FROM articles WHERE story_id=?", (sid,)
            ).fetchall()
            per_article = [Counter(loads(r["countries"], {}) or {}) for r in rows]
            countries = story_countries(per_article)
            regions = self.regions.for_countries(set(countries))
            category = None
            if self.classifier is not None:
                cent = self.conn.execute(
                    "SELECT centroid FROM stories WHERE id=?", (sid,)
                ).fetchone()["centroid"]
                category, _ = self.classifier.classify(from_blob(cent))
            self.conn.execute(
                "UPDATE stories SET countries=?, regions=?, category=? WHERE id=?",
                (dumps(countries), dumps(regions), category, sid),
            )

    def _storylines(self, story_ids: set[int], stats: ProcessStats) -> None:
        since = iso(utcnow() - timedelta(days=self.cc.storyline_window_days))
        pool = self.conn.execute(
            "SELECT id, centroid, countries, storyline_id FROM stories"
            " WHERE merged_into IS NULL AND last_article_at >= ? AND embedding_model = ?",
            (since, self.embedder.model),
        ).fetchall()
        if len(pool) < 2:
            return
        ids = [r["id"] for r in pool]
        cents = np.stack([from_blob(r["centroid"]) for r in pool])
        places = [set(loads(r["countries"], [])) for r in pool]
        line_of = {r["id"]: r["storyline_id"] for r in pool}
        for sid in story_ids:
            if sid not in ids or line_of.get(sid):
                continue
            i = ids.index(sid)
            sims = cents @ cents[i]
            for j in np.argsort(-sims):
                j = int(j)
                if j == i:
                    continue
                if sims[j] < self.cc.storyline_threshold:
                    break
                if not (places[i] & places[j]):
                    continue  # storylines need a shared place
                other = ids[j]
                line = line_of.get(other)
                now = iso(utcnow())
                if not line:
                    cur = self.conn.execute(
                        "INSERT INTO storylines (created_at, updated_at, centroid) VALUES (?,?,?)",
                        (now, now, to_blob(cents[j])),
                    )
                    line = cur.lastrowid
                    self.conn.execute(
                        "UPDATE stories SET storyline_id=? WHERE id=?", (line, other)
                    )
                    line_of[other] = line
                self.conn.execute("UPDATE stories SET storyline_id=? WHERE id=?", (line, sid))
                self.conn.execute(
                    "UPDATE storylines SET updated_at=? WHERE id=?", (now, line)
                )
                line_of[sid] = line
                stats.storylines_linked += 1
                break

    # --- entry point -----------------------------------------------------------------
    def process(self) -> ProcessStats:
        stats = ProcessStats()
        rows = self.conn.execute(
            "SELECT * FROM articles WHERE processed=0 ORDER BY published_at, id"
        ).fetchall()
        if not rows:
            return stats
        lead_chars = self.cfg.lifecycle.lead_chars
        for r in rows:
            lead = lead_of(r["title"], r["text"], r["summary"], 600)
            src = self.registry.get(r["source_id"])
            declared = r["lang"] or (src.languages[0] if src else None)
            lang = detect(f"{r['title']} {lead}", default=declared) or declared
            countries = self.gaz.countries(f"{r['title']} {lead}")
            self.conn.execute(
                "UPDATE articles SET lang=?, countries=? WHERE id=?",
                (lang, dumps(dict(countries)), r["id"]),
            )
        stats.processed = len(rows)
        rows = self.conn.execute(
            f"SELECT * FROM articles WHERE id IN ({','.join('?' * len(rows))})"
            " ORDER BY published_at, id",
            [r["id"] for r in rows],
        ).fetchall()

        fresh = self._dedup(rows, stats)
        touched: set[int] = set()
        if fresh:
            texts = [
                embedding_text(
                    normalize(r["title"]),
                    lead_of(r["title"], r["text"], r["summary"], lead_chars),
                    self.cfg.embeddings.max_chars,
                )
                for r in fresh
            ]
            vecs = self.embedder.embed(texts)
            for r, v in zip(fresh, vecs, strict=True):
                self.conn.execute(
                    "UPDATE articles SET embedding=?, embedding_model=? WHERE id=?",
                    (to_blob(v), self.embedder.model, r["id"]),
                )
            touched = self._cluster(fresh, vecs, stats)
        touched |= self._attach_duplicates([r["id"] for r in rows])
        self._refresh_counts(touched)
        touched = self._merge(touched, stats)
        self._refresh_counts(touched)
        self._attributes(touched)
        self._storylines(touched, stats)
        self.conn.commit()
        return stats
