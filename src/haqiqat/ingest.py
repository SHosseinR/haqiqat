"""Fetch new articles from RSS/Atom feeds and news sitemaps, then extract main text.

Rules we hold ourselves to (docs/methodology.md, "Legal hygiene"): only feeds and
sitemaps publishers expose, robots.txt respected, polite per-host delays, conditional
requests, a clear user agent, no paywall circumvention. Full text is stored privately for
analysis; we publish only headlines, short excerpts, links and our own summaries.
"""

from __future__ import annotations

import calendar
import html
import logging
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import feedparser
import httpx

from .config import Config
from .db import iso, utcnow
from .sources import Feed, Registry, Source

log = logging.getLogger(__name__)

_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|ref$|ref_src$|at_|cmpid$|ocid$|__twitter)")
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def is_web_url(url: str | None) -> bool:
    """Only http(s) links are stored: a feed must never inject `javascript:` or `data:` URLs
    into our pages."""
    if not url:
        return False
    parts = urlsplit(url.strip())
    return parts.scheme.lower() in ("http", "https") and bool(parts.netloc)


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not _TRACKING.match(k)]
    return urlunsplit(
        (parts.scheme.lower() or "https", parts.netloc.lower(), parts.path or "/",
         urlencode(query), "")
    )


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    return _WS.sub(" ", html.unescape(_TAGS.sub(" ", value))).strip()


@dataclass
class FeedItem:
    url: str
    title: str
    summary: str
    published: datetime


@dataclass
class IngestStats:
    feeds_ok: int = 0
    feeds_failed: int = 0
    feeds_not_modified: int = 0
    new_articles: int = 0
    texts_extracted: int = 0
    errors: list[str] = field(default_factory=list)


class Fetcher:
    """HTTP client with robots.txt checks and a per-host politeness delay."""

    def __init__(self, cfg: Config, client: httpx.Client | None = None):
        self.cfg = cfg
        self.client = client or httpx.Client(
            headers={"User-Agent": cfg.http.user_agent},
            timeout=cfg.http.timeout,
            follow_redirects=True,
        )
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}

    def allowed(self, url: str) -> bool:
        host = urlsplit(url).netloc
        if host not in self._robots:
            rp = RobotFileParser()
            try:
                r = self.client.get(f"{urlsplit(url).scheme}://{host}/robots.txt")
                if r.status_code >= 400:
                    self._robots[host] = None  # no robots.txt: everything allowed
                else:
                    rp.parse(r.text.splitlines())
                    self._robots[host] = rp
            except httpx.HTTPError:
                self._robots[host] = None
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(self.cfg.http.user_agent, url)

    def get(self, url: str, headers: dict | None = None) -> httpx.Response:
        host = urlsplit(url).netloc
        wait = self.cfg.http.per_host_delay - (time.monotonic() - self._last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        try:
            return self.client.get(url, headers=headers or {})
        finally:
            self._last_hit[host] = time.monotonic()


def _entry_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), tz=UTC)
    return None


def parse_rss(content: bytes, now: datetime) -> list[FeedItem]:
    parsed = feedparser.parse(content)
    items = []
    for e in parsed.entries:
        link = e.get("link")
        title = strip_html(e.get("title"))
        if not is_web_url(link) or not title:
            continue
        published = _entry_time(e) or now
        items.append(FeedItem(
            url=canonical_url(link),
            title=title,
            summary=strip_html(e.get("summary") or e.get("description")),
            published=min(published, now),
        ))
    return items


_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def parse_sitemap(content: bytes, now: datetime) -> tuple[list[FeedItem], list[str]]:
    """Items from a Google News sitemap, plus child sitemap URLs if it is an index."""
    root = ET.fromstring(content)
    children = [
        loc.text.strip() for loc in root.findall("sm:sitemap/sm:loc", _NS) if loc.text
    ]
    items = []
    for url in root.findall("sm:url", _NS):
        loc = url.findtext("sm:loc", namespaces=_NS)
        title = url.findtext("news:news/news:title", namespaces=_NS)
        if not is_web_url(loc) or not title:
            continue
        published = _parse_date(url.findtext("news:news/news:publication_date", namespaces=_NS))
        items.append(FeedItem(
            url=canonical_url(loc), title=strip_html(title), summary="",
            published=min(published or now, now),
        ))
    return items, children


# trafilatura drops the zero-width non-joiner, which Persian needs (مقام‌ها vs مقامها).
# Protect it with a placeholder that trafilatura keeps, and restore it afterwards.
_ZWNJ_FORMS = re.compile(r"\u200c|&zwnj;|&#8204;|&#x200c;", re.IGNORECASE)
_ZWNJ_PLACEHOLDER = "\u034f"  # combining grapheme joiner: survives, never used in news text


def extract_text(html_text: str) -> str | None:
    import trafilatura

    protected = _ZWNJ_FORMS.sub(_ZWNJ_PLACEHOLDER, html_text)
    text = trafilatura.extract(
        protected, include_comments=False, include_tables=False, favor_precision=True
    )
    return text.replace(_ZWNJ_PLACEHOLDER, "\u200c") if text else text


class Ingestor:
    def __init__(self, conn: sqlite3.Connection, cfg: Config, registry: Registry,
                 fetcher: Fetcher | None = None):
        self.conn = conn
        self.cfg = cfg
        self.registry = registry
        self.fetcher = fetcher or Fetcher(cfg)

    def _fetch_feed(self, feed: Feed, stats: IngestStats) -> bytes | None:
        state = self.conn.execute(
            "SELECT etag, last_modified, error_count FROM feed_state WHERE url = ?", (feed.url,)
        ).fetchone()
        headers = {}
        if state and state["etag"]:
            headers["If-None-Match"] = state["etag"]
        if state and state["last_modified"]:
            headers["If-Modified-Since"] = state["last_modified"]
        now = iso(utcnow())
        try:
            if not self.fetcher.allowed(feed.url):
                raise RuntimeError("disallowed by robots.txt")
            r = self.fetcher.get(feed.url, headers)
            if r.status_code == 304:
                stats.feeds_not_modified += 1
                self.conn.execute(
                    "UPDATE feed_state SET last_fetch_at=?, last_status='304' WHERE url=?",
                    (now, feed.url),
                )
                return None
            r.raise_for_status()
        except Exception as e:
            stats.feeds_failed += 1
            stats.errors.append(f"{feed.url}: {e}")
            self.conn.execute(
                "INSERT INTO feed_state (url, last_fetch_at, last_status, error_count)"
                " VALUES (?,?,?,1) ON CONFLICT(url) DO UPDATE SET"
                " last_fetch_at=excluded.last_fetch_at,"
                " last_status=excluded.last_status, error_count=feed_state.error_count+1",
                (feed.url, now, str(e)[:200]),
            )
            return None
        stats.feeds_ok += 1
        self.conn.execute(
            "INSERT INTO feed_state (url, etag, last_modified, last_fetch_at, last_status,"
            " error_count)"
            " VALUES (?,?,?,?,?,0) ON CONFLICT(url) DO UPDATE SET etag=excluded.etag,"
            " last_modified=excluded.last_modified, last_fetch_at=excluded.last_fetch_at,"
            " last_status=excluded.last_status, error_count=0",
            (feed.url, r.headers.get("etag"), r.headers.get("last-modified"), now,
             str(r.status_code)),
        )
        return r.content

    def _items(self, feed: Feed, content: bytes, now: datetime) -> list[FeedItem]:
        if feed.kind == "rss":
            return parse_rss(content, now)
        items, children = parse_sitemap(content, now)
        for child in children[:3]:
            try:
                r = self.fetcher.get(child)
                r.raise_for_status()
                items.extend(parse_sitemap(r.content, now)[0])
            except Exception as e:
                log.warning("sitemap child %s: %s", child, e)
        return items

    def ingest_source(self, source: Source, stats: IngestStats) -> list[int]:
        now = utcnow()
        cutoff = now - timedelta(hours=self.cfg.http.lookback_hours)
        new_ids = []
        for feed in source.feeds:
            if not feed.enabled:
                continue
            content = self._fetch_feed(feed, stats)
            if content is None:
                continue
            try:
                items = self._items(feed, content, now)
            except Exception as e:
                stats.errors.append(f"{feed.url}: parse error: {e}")
                continue
            items = sorted(items, key=lambda i: i.published, reverse=True)
            for item in items[: self.cfg.http.max_items_per_feed]:
                if item.published < cutoff:
                    continue
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO articles (source_id, url, title, summary, lang,"
                    " published_at, fetched_at) VALUES (?,?,?,?,?,?,?)",
                    (source.id, item.url, item.title, item.summary,
                     source.feed_language(feed), iso(item.published), iso(now)),
                )
                if cur.rowcount:
                    new_ids.append(cur.lastrowid)
        self.conn.commit()
        return new_ids

    def fetch_texts(self, article_ids: list[int], stats: IngestStats) -> None:
        for aid in article_ids[: self.cfg.http.max_full_text_per_run]:
            row = self.conn.execute("SELECT url FROM articles WHERE id=?", (aid,)).fetchone()
            try:
                if not self.fetcher.allowed(row["url"]):
                    continue
                r = self.fetcher.get(row["url"])
                r.raise_for_status()
                text = extract_text(r.text)
            except Exception as e:
                log.info("text fetch failed for %s: %s", row["url"], e)
                continue
            if text:
                self.conn.execute("UPDATE articles SET text=? WHERE id=?", (text, aid))
                stats.texts_extracted += 1
        self.conn.commit()

    def run(self, limit_sources: int | None = None, source_ids: list[str] | None = None
            ) -> IngestStats:
        stats = IngestStats()
        sources = self.registry.enabled()
        if source_ids:
            sources = [s for s in sources if s.id in source_ids]
        if limit_sources:
            sources = sources[:limit_sources]
        new_ids: list[int] = []
        for src in sources:
            ids = self.ingest_source(src, stats)
            new_ids.extend(ids)
        stats.new_articles = len(new_ids)
        if self.cfg.http.fetch_full_text:
            self.fetch_texts(new_ids, stats)
        return stats
