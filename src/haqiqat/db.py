"""SQLite storage. One file, no server: fits a solo operator and a tiny VPS."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY,
    source_id       TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    summary         TEXT,
    text            TEXT,
    lang            TEXT,
    published_at    TEXT NOT NULL,
    fetched_at      TEXT NOT NULL,
    processed       INTEGER NOT NULL DEFAULT 0,
    minhash         BLOB,
    dup_of          INTEGER REFERENCES articles(id),
    embedding       BLOB,
    embedding_model TEXT,
    story_id        INTEGER REFERENCES stories(id),
    countries       TEXT
);
CREATE INDEX IF NOT EXISTS idx_articles_story ON articles(story_id);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_processed ON articles(processed);

CREATE TABLE IF NOT EXISTS stories (
    id                  INTEGER PRIMARY KEY,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    first_article_at    TEXT NOT NULL,
    last_article_at     TEXT NOT NULL,
    centroid            BLOB NOT NULL,
    embedding_model     TEXT NOT NULL,
    n_articles          INTEGER NOT NULL DEFAULT 0,
    storyline_id        INTEGER REFERENCES storylines(id),
    merged_into         INTEGER REFERENCES stories(id),
    category            TEXT,
    countries           TEXT,
    regions             TEXT,
    score               REAL NOT NULL DEFAULT 0,
    score_parts         TEXT,
    current_version     INTEGER NOT NULL DEFAULT 0,
    last_synth_at       TEXT,
    last_synth_article_ids TEXT,
    last_synth_groups   TEXT
);
CREATE INDEX IF NOT EXISTS idx_stories_last ON stories(last_article_at);

CREATE TABLE IF NOT EXISTS storylines (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    centroid    BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS syntheses (
    id               INTEGER PRIMARY KEY,
    story_id         INTEGER NOT NULL REFERENCES stories(id),
    version          INTEGER NOT NULL,
    created_at       TEXT NOT NULL,
    trigger          TEXT NOT NULL,
    provider         TEXT NOT NULL,
    model            TEXT NOT NULL,
    prompt_version   TEXT NOT NULL,
    input_article_ids TEXT NOT NULL,
    output           TEXT NOT NULL,
    input_tokens     INTEGER NOT NULL DEFAULT 0,
    output_tokens    INTEGER NOT NULL DEFAULT 0,
    cost_usd         REAL NOT NULL DEFAULT 0,
    UNIQUE(story_id, version)
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id            INTEGER PRIMARY KEY,
    ts            TEXT NOT NULL,
    day           TEXT NOT NULL,
    stage         TEXT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    ok            INTEGER NOT NULL,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_usage_day ON llm_usage(day);

CREATE TABLE IF NOT EXISTS embedding_cache (
    hash    TEXT NOT NULL,
    model   TEXT NOT NULL,
    vector  BLOB NOT NULL,
    PRIMARY KEY (hash, model)
);

CREATE TABLE IF NOT EXISTS feed_state (
    url            TEXT PRIMARY KEY,
    etag           TEXT,
    last_modified  TEXT,
    last_fetch_at  TEXT,
    last_status    TEXT,
    error_count    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS publications (
    id           INTEGER PRIMARY KEY,
    channel      TEXT NOT NULL,
    lang         TEXT NOT NULL,
    kind         TEXT NOT NULL,
    story_id     INTEGER,
    version      INTEGER,
    message_id   TEXT,
    published_at TEXT NOT NULL,
    day          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pub_story ON publications(story_id, channel);
"""


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value: str | None, default=None):
    if value is None:
        return default
    return json.loads(value)


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn
