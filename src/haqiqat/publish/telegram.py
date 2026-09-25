"""Telegram channels: one per language. The bot must be an admin of each channel.

- A story is posted once it has an LLM summary and crosses `min_score`, up to
  `max_posts_per_day` per channel.
- When a posted story gets a new version within `edit_window_hours`, the post is edited in
  place instead of posting again, so the channel stays calm.
- A daily digest of the top stories goes out at `digest_hour_local` (Tehran time).
"""

from __future__ import annotations

import html
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from ..config import Config
from ..db import iso, parse_iso, utcnow
from ..i18n import fmt_time, num, t
from ..labels import CONFIRMED, CORROBORATED, DISPUTED, LABEL_NAMES
from ..sources import Registry
from ..views import LLM, StoryView, top_stories

log = logging.getLogger(__name__)

MAX_LEN = 4000
ICON = {CONFIRMED: "✅", CORROBORATED: "☑️", DISPUTED: "⚖️"}


def story_url(cfg: Config, lang: str, story_id: int) -> str:
    return f"{cfg.site.base_url.rstrip('/')}/{lang}/story/{story_id}/"


def format_story(cfg: Config, registry: Registry, s: StoryView, lang: str) -> str:
    def e(text: str) -> str:
        return html.escape(text, quote=False)

    lines = [f"<b>{e(s.title[lang])}</b>", "", e(s.summary.get(lang, ""))]
    facts = [f for f in s.facts if f.label in (CONFIRMED, CORROBORATED, DISPUTED)][:4]
    if facts:
        lines.append("")
        for f in facts:
            text = f.text.get(lang) or f.text["en"]
            if f.attributed_to:
                text += f" ({t(lang, 'according_to', x=f.attributed_to)})"
            label = LABEL_NAMES[f.label][lang]
            lines.append(f"{ICON.get(f.label, '•')} {e(text)} <i>[{label}]</i>")
    camps = " · ".join(
        f"{registry.lenses.camp_name(c, lang)} {num(lang, n)}" for c, n in s.camps.most_common()
    )
    lines += ["", f"🔎 {t(lang, 'independent_sources', n=s.n_groups)} — {e(camps)}"]
    if s.blindspot:
        lines.append(e(t(lang, "blindspot", camp=registry.lenses.camp_name(s.blindspot, lang))))
    lines.append(f'<a href="{story_url(cfg, lang, s.id)}">{e(t(lang, "all_reports"))} →</a>')
    text = "\n".join(lines)
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 1] + "…"


def format_digest(cfg: Config, stories: list[StoryView], lang: str, now: datetime) -> str:
    def e(text: str) -> str:
        return html.escape(text, quote=False)

    head = f"<b>{e(t(lang, 'top_stories'))} — {e(fmt_time(now, lang, cfg.telegram.timezone))}</b>"
    lines = [head, ""]
    for i, s in enumerate(stories, 1):
        lines.append(
            f'{num(lang, i)}. <a href="{story_url(cfg, lang, s.id)}">{e(s.title[lang])}</a>'
            f" — {e(t(lang, 'n_sources_short', n=s.n_groups))}"
        )
    return "\n".join(lines)[:MAX_LEN]


class TelegramAPI:
    def __init__(self, token: str, client: httpx.Client | None = None):
        self.base = f"https://api.telegram.org/bot{token}"
        self.http = client or httpx.Client(timeout=30)

    def call(self, method: str, **params) -> dict:
        r = self.http.post(f"{self.base}/{method}", json=params)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram {method}: {data.get('description')}")
        return data["result"]

    def send(self, chat: str, text: str) -> str:
        res = self.call("sendMessage", chat_id=chat, text=text, parse_mode="HTML",
                        disable_web_page_preview=True)
        return str(res["message_id"])

    def edit(self, chat: str, message_id: str, text: str) -> None:
        self.call("editMessageText", chat_id=chat, message_id=int(message_id), text=text,
                  parse_mode="HTML", disable_web_page_preview=True)


@dataclass
class PublishStats:
    posted: int = 0
    edited: int = 0
    digests: int = 0
    previews: list[str] = field(default_factory=list)


class TelegramPublisher:
    def __init__(self, conn: sqlite3.Connection, cfg: Config, registry: Registry,
                 api: TelegramAPI | None = None, dry_run: bool = False):
        self.conn = conn
        self.cfg = cfg
        self.registry = registry
        self.api = api
        self.dry_run = dry_run

    def _record(self, chat: str, lang: str, kind: str, story_id: int | None,
                version: int | None, message_id: str | None, now: datetime) -> None:
        if self.dry_run:
            return
        self.conn.execute(
            "INSERT INTO publications (channel, lang, kind, story_id, version, message_id,"
            " published_at, day) VALUES (?,?,?,?,?,?,?,?)",
            (chat, lang, kind, story_id, version, message_id, iso(now), self._local_day(now)),
        )
        self.conn.commit()

    def _local_day(self, now: datetime) -> str:
        return now.astimezone(ZoneInfo(self.cfg.telegram.timezone)).strftime("%Y-%m-%d")

    def _send(self, chat: str, text: str, stats: PublishStats) -> str | None:
        if self.dry_run or self.api is None:
            stats.previews.append(f"--- to {chat} ---\n{text}")
            return None
        return self.api.send(chat, text)

    def run(self, now: datetime | None = None) -> PublishStats:
        tc = self.cfg.telegram
        now = now or utcnow()
        stats = PublishStats()
        stories = top_stories(self.conn, self.cfg, self.registry, now=now, limit=100)
        eligible = [s for s in stories if s.kind == LLM and s.score >= tc.min_score]
        today = self._local_day(now)
        for lang, chat in tc.channels.items():
            posted_today = self.conn.execute(
                "SELECT COUNT(*) FROM publications WHERE channel=? AND kind='story' AND day=?",
                (chat, today),
            ).fetchone()[0]
            for s in eligible:
                pub = self.conn.execute(
                    "SELECT * FROM publications WHERE channel=? AND story_id=? AND kind='story'"
                    " ORDER BY id DESC LIMIT 1", (chat, s.id),
                ).fetchone()
                text = format_story(self.cfg, self.registry, s, lang)
                if pub is None:
                    if posted_today >= tc.max_posts_per_day:
                        continue
                    mid = self._send(chat, text, stats)
                    self._record(chat, lang, "story", s.id, s.synth.version, mid, now)
                    posted_today += 1
                    stats.posted += 1
                elif (pub["version"] or 0) < s.synth.version and pub["message_id"]:
                    age = now - parse_iso(pub["published_at"])
                    if age > timedelta(hours=tc.edit_window_hours):
                        continue
                    if self.dry_run or self.api is None:
                        stats.previews.append(f"--- edit {chat}#{pub['message_id']} ---\n{text}")
                    else:
                        try:
                            self.api.edit(chat, pub["message_id"], text)
                        except RuntimeError as e:
                            log.warning("edit failed: %s", e)
                            continue
                    if not self.dry_run:
                        self.conn.execute("UPDATE publications SET version=? WHERE id=?",
                                          (s.synth.version, pub["id"]))
                        self.conn.commit()
                    stats.edited += 1
            local_hour = now.astimezone(ZoneInfo(tc.timezone)).hour
            sent_digest = self.conn.execute(
                "SELECT COUNT(*) FROM publications WHERE channel=? AND kind='digest' AND day=?",
                (chat, today),
            ).fetchone()[0]
            if local_hour >= tc.digest_hour_local and not sent_digest and stories:
                text = format_digest(self.cfg, stories[: tc.digest_size], lang, now)
                mid = self._send(chat, text, stats)
                self._record(chat, lang, "digest", None, None, mid, now)
                stats.digests += 1
        return stats
