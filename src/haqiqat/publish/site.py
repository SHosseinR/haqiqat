"""Static site generator: bilingual (EN / FA with RTL), almost no JavaScript, easy to mirror.

Pages: /{lang}/ (world), /{lang}/region/{id}/, /{lang}/story/{id}/,
/{lang}/storyline/{id}/, /{lang}/sources/, /{lang}/about/, plus /api/*.json and
/{lang}/feed.xml. Story pages are never deleted, so links shared on Telegram keep working
after a story leaves the front page.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import asdict
from datetime import datetime
from email.utils import format_datetime
from importlib import resources
from xml.sax.saxutils import escape

from jinja2 import Environment, PackageLoader, select_autoescape

from ..config import Config
from ..db import iso, utcnow
from ..i18n import OWNERSHIP, RELIABILITY, fmt_time, num, t
from ..labels import LABEL_NAMES
from ..nlp.classify import Taxonomy
from ..nlp.geo import Gazetteer, Regions
from ..sources import Registry
from ..views import StoryView, storyline_stories, top_stories


def story_dict(s: StoryView) -> dict:
    """Public JSON for a story (no full article text)."""
    return {
        "id": s.id,
        "kind": s.kind,
        "score": s.score,
        "score_parts": s.score_parts,
        "first_article_at": iso(s.first_article_at),
        "last_article_at": iso(s.last_article_at),
        "countries": s.countries,
        "regions": s.regions,
        "category": s.category,
        "storyline_id": s.storyline_id,
        "title": s.title,
        "summary": s.summary,
        "facts": [asdict(f) for f in s.facts],
        "disputes": s.disputes,
        "extractive": {k: [asdict(x) for x in v] for k, v in s.extractive.items()},
        "n_independent_groups": s.n_groups,
        "camps": dict(s.camps),
        "blindspot": s.blindspot,
        "synthesis": (
            {**asdict(s.synth), "created_at": iso(s.synth.created_at)} if s.synth else None
        ),
        "articles": [
            {
                "id": a.id, "title": a.title, "url": a.url, "source": a.source_id,
                "lang": a.lang, "published_at": iso(a.published_at), "camp": a.camp,
                "is_copy": a.is_dup,
            }
            for a in s.articles
        ],
    }


class SiteBuilder:
    def __init__(self, conn: sqlite3.Connection, cfg: Config, registry: Registry,
                 regions: Regions, gazetteer: Gazetteer, taxonomy: Taxonomy):
        self.conn = conn
        self.cfg = cfg
        self.registry = registry
        self.regions = regions
        self.gaz = gazetteer
        self.taxonomy = taxonomy
        self.out = cfg.path(cfg.site.output_dir)
        self.env = Environment(
            loader=PackageLoader("haqiqat", "templates"),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        tz = cfg.site.timezone
        lenses = registry.lenses
        self.env.globals.update(
            t=t, num=num, cfg=cfg, regions=regions, LABEL_NAMES=LABEL_NAMES,
            OWNERSHIP=OWNERSHIP, RELIABILITY=RELIABILITY, lenses=lenses,
            camp_name=lenses.camp_name,
            country_name=lambda code, lang: self.gaz.display(code, lang),
            topic_name=lambda tid, lang: self.taxonomy.name(tid, lang),
            fmt_time=lambda dt, lang, with_date=True: fmt_time(dt, lang, tz, with_date),
            source=registry.get,
        )

    def _write(self, rel: str, content: str) -> None:
        path = self.out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _render(self, template: str, rel: str, **ctx) -> None:
        ctx.setdefault("built_at", utcnow())
        if "lang" in ctx:
            # Relative links everywhere, so the site works from any mirror or path.
            ctx["root"] = "../" * ctx.get("depth", 0)
            langs = ctx["langs"]
            ctx["other"] = next((x for x in langs if x != ctx["lang"]), ctx["lang"])
        self._write(rel, self.env.get_template(template).render(**ctx))

    def build(self, now: datetime | None = None) -> dict[str, int]:
        now = now or utcnow()
        self.out.mkdir(parents=True, exist_ok=True)
        assets = resources.files("haqiqat").joinpath("static")
        dest = self.out / "assets"
        dest.mkdir(exist_ok=True)
        for f in assets.iterdir():
            if f.is_file():
                shutil.copyfile(str(f), dest / f.name)

        stories = top_stories(self.conn, self.cfg, self.registry, now=now, limit=300)
        per_page = self.cfg.site.stories_per_page
        langs = self.cfg.site.languages
        counts = {"stories": len(stories), "pages": 0}

        self._render("landing.html", "index.html", langs=langs)
        for lang in langs:
            base = dict(lang=lang, langs=langs, depth=1)
            world = next((rid for rid in self.regions.order
                          if not self.regions.regions[rid].countries), None)
            self._render("list.html", f"{lang}/index.html", stories=stories[:per_page],
                         region_id=None, nav_region=world, **base)
            for rid in self.regions.order:
                r = self.regions.regions[rid]
                if not r.countries:
                    continue
                subset = [s for s in stories if rid in s.regions][:per_page]
                self._render("list.html", f"{lang}/region/{rid}/index.html", stories=subset,
                             region_id=rid, nav_region=rid, **{**base, "depth": 3})
            for s in stories:
                self._render("story.html", f"{lang}/story/{s.id}/index.html", s=s,
                             **{**base, "depth": 3})
                counts["pages"] += 1
            lines = {s.storyline_id for s in stories if s.storyline_id}
            for line_id in lines:
                members = storyline_stories(self.conn, self.cfg, self.registry, line_id)
                self._render("storyline.html", f"{lang}/storyline/{line_id}/index.html",
                             members=members, line_id=line_id, **{**base, "depth": 3})
            self._render("sources.html", f"{lang}/sources/index.html",
                         sources=sorted(self.registry.sources.values(), key=lambda x: x.id),
                         **{**base, "depth": 2})
            self._render("about.html", f"{lang}/about/index.html", **{**base, "depth": 2})
            self._write(f"{lang}/feed.xml", self._rss(stories[:50], lang))

        self._redirect_merged(langs)
        api = [story_dict(s) for s in stories]
        self._write("api/stories.json", json.dumps(
            {"generated_at": iso(now), "stories": api}, ensure_ascii=False, indent=1))
        for d in api:
            self._write(f"api/story/{d['id']}.json", json.dumps(d, ensure_ascii=False, indent=1))
        return counts

    def _redirect_merged(self, langs: list[str]) -> None:
        rows = self.conn.execute(
            "SELECT id, merged_into FROM stories WHERE merged_into IS NOT NULL"
        ).fetchall()
        for r in rows:
            for lang in langs:
                page = self.out / lang / "story" / str(r["id"]) / "index.html"
                if page.exists():
                    target = f"../{r['merged_into']}/"
                    page.write_text(
                        f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" '
                        f'content="0; url={target}"><link rel="canonical" href="{target}">'
                        f'<a href="{target}">→</a>', encoding="utf-8")

    def _rss(self, stories: list[StoryView], lang: str) -> str:
        base = self.cfg.site.base_url.rstrip("/")
        items = []
        for s in stories:
            link = f"{base}/{lang}/story/{s.id}/"
            desc = s.summary.get(lang) or ""
            items.append(
                f"<item><title>{escape(s.title.get(lang, ''))}</title><link>{link}</link>"
                f"<guid>{link}</guid><pubDate>{format_datetime(s.last_article_at)}</pubDate>"
                f"<description>{escape(desc)}</description></item>"
            )
        title = escape(self.cfg.site.title.get(lang, "Haqiqat"))
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n<rss version="2.0"><channel>'
            f"<title>{title}</title><link>{base}/{lang}/</link>"
            f"<description>{escape(t(lang, 'tagline'))}</description><language>{lang}</language>"
            + "".join(items) + "</channel></rss>\n"
        )
