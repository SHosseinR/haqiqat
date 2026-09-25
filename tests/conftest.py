"""Shared fixtures: a throwaway project (config + sources) wired to fake providers and a mock
HTTP transport, so the whole pipeline runs offline and deterministically."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

import httpx
import pytest
import yaml

from haqiqat.config import load_config, with_fake_providers
from haqiqat.ingest import Fetcher
from haqiqat.pipeline import App

REPO = Path(__file__).resolve().parent.parent


def source(id, group, origin, lang, iran=None, kind="private", country="IR"):
    lenses = {"origin": origin}
    if iran:
        lenses["iran"] = iran
    return {
        "id": id,
        "name": {"en": id.replace("-", " ").title(), "fa": f"رسانه {id}"},
        "homepage": f"https://{id}.test",
        "languages": [lang],
        "country": country,
        "type": "online",
        "ownership": {"kind": kind},
        "independence_group": group,
        "lenses": lenses,
        "feeds": [{"url": f"https://{id}.test/rss"}],
    }


TEST_SOURCES = [
    source("state", "ir-gov", "iran", "fa", "ir_state", kind="state"),
    source("reform", "reform", "iran", "fa", "ir_reformist"),
    source("copyco", "copyco", "iran", "fa", "ir_principlist"),
    source("abroad", "abroad", "western", "fa", "foreign_state_persian", kind="public",
           country="GB"),
    source("wire", "wire", "western", "en", country="GB"),
    source("regional", "regional", "qatar", "en", kind="state", country="QA"),
]

DRONE_FA = (
    "مقام‌های ایران می‌گویند حمله پهپادی به یک مرکز در اصفهان ناکام ماند و پهپادها پیش از "
    "رسیدن به هدف رهگیری شدند. به گفته این مقام‌ها حمله خسارت جدی نداشت و وضعیت در اصفهان "
    "عادی است و تحقیقات درباره منشأ حمله پهپادی ادامه دارد."
)


def article(slug, title, desc, minutes_ago=30):
    return {"slug": slug, "title": title, "desc": desc, "minutes_ago": minutes_ago}


FEEDS_ROUND_1 = {
    "state": [article("drone", "حمله پهپادی به اصفهان", DRONE_FA, 90)],
    # A near-verbatim copy of the state report: must be detected as a duplicate.
    "copyco": [article("drone-copy", "حمله پهپادی به اصفهان ناکام ماند", DRONE_FA, 80)],
    "abroad": [article("drone", "گزارش حمله پهپادی در اصفهان ایران",
                       "گزارش‌ها از حمله پهپادی به اصفهان در ایران حکایت دارد.", 70)],
    "wire": [
        article("drone", "Drone attack hits Isfahan, Iran",
                "Several drones attacked a site in Isfahan, Iran, officials said.", 60),
        article("quake", "Earthquake strikes eastern Turkey",
                "A strong earthquake struck eastern Turkey on Monday, killing at least 12.", 50),
    ],
    "regional": [
        article("quake", "Strong earthquake kills 12 in eastern Turkey",
                "An earthquake in eastern Turkey killed 12 people, officials in Ankara said.", 45),
    ],
    "reform": [article("election", "نامزدهای انتخابات شورای شهر تهران اعلام شدند",
                       "فهرست نامزدهای انتخابات شورای شهر تهران منتشر شد.", 40)],
}

# Round 2: a new independent group (reform) reports the drone attack.
FEEDS_ROUND_2 = {
    **FEEDS_ROUND_1,
    "reform": FEEDS_ROUND_1["reform"] + [
        article("drone2", "جزئیات تازه از حمله پهپادی اصفهان",
                "روزنامه‌نگاران در اصفهان از حمله پهپادی و رهگیری پهپادها در ایران خبر دادند.", 10),
    ],
}


def rss(source_id: str, items: list[dict], now: datetime) -> bytes:
    body = "".join(
        f"<item><title>{escape(a['title'])}</title>"
        f"<link>https://{source_id}.test/{a['slug']}</link>"
        f"<description>{escape(a['desc'])}</description>"
        f"<pubDate>{format_datetime(now - timedelta(minutes=a['minutes_ago']))}</pubDate></item>"
        for a in items
    )
    return (f'<?xml version="1.0"?><rss version="2.0"><channel><title>{source_id}</title>'
            f"{body}</channel></rss>").encode()


class FakeWeb:
    """Serves feeds and article pages for the *.test sources."""

    def __init__(self, feeds: dict[str, list[dict]]):
        self.feeds = feeds
        self.now = datetime.now(UTC)
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        host = request.url.host
        sid = host.removesuffix(".test")
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/rss":
            return httpx.Response(200, content=rss(sid, self.feeds.get(sid, []), self.now),
                                  headers={"content-type": "application/rss+xml"})
        for a in self.feeds.get(sid, []):
            if path == f"/{a['slug']}":
                html = (f"<html><body><article><h1>{escape(a['title'])}</h1>"
                        f"<p>{escape(a['desc'])}</p></article></body></html>")
                return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(404)


def build_project(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    for name in ("lenses.yaml", "regions.yaml", "taxonomy.yaml", "gazetteer.yaml", "style.yaml"):
        shutil.copy(REPO / "config" / name, tmp_path / "config" / name)
    src_dir = tmp_path / "sources"
    src_dir.mkdir()
    for s in TEST_SOURCES:
        (src_dir / f"{s['id']}.yaml").write_text(yaml.safe_dump(s, allow_unicode=True),
                                                   encoding="utf-8")
    cfg = yaml.safe_load((REPO / "config" / "config.example.yaml").read_text(encoding="utf-8"))
    cfg["database"] = "data/test.db"
    cfg["http"]["per_host_delay"] = 0
    cfg["clustering"].update(join_threshold=0.3, strong_threshold=0.6, merge_threshold=0.85,
                             storyline_threshold=0.3)
    cfg["lifecycle"].update(debounce_hours_top=0, debounce_hours_other=0)
    cfg["site"]["base_url"] = "https://haqiqat.test"
    cfg["telegram"]["channels"] = {"en": "@test_en", "fa": "@test_fa"}
    cfg["telegram"]["min_score"] = 0
    (tmp_path / "config" / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True),
                                                     encoding="utf-8")
    return tmp_path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return build_project(tmp_path)


def make_app(project: Path, web: FakeWeb) -> App:
    cfg = with_fake_providers(load_config(project / "config" / "config.yaml"))
    client = httpx.Client(transport=httpx.MockTransport(web.handler))
    return App(cfg, fetcher=Fetcher(cfg, client=client))


@pytest.fixture
def app_factory(project):
    def factory(feeds=FEEDS_ROUND_1):
        return make_app(project, FakeWeb(feeds))

    return factory
