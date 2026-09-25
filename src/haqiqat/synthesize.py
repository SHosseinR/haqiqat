"""LLM synthesis: one call per story version, with a structured JSON output.

New stories get a full synthesis. Updates send only the previous facts plus the new
articles, and the model reports which new articles support or contradict each existing
fact; code merges that into the stored support lists. Every version is stored with its
model, prompt version, inputs and cost.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Literal

from jinja2 import Environment
from pydantic import BaseModel, ValidationError

from .budget import Budget, chat_cost
from .cluster import lead_of
from .config import Config
from .coverage import ArticleInfo, Coverage
from .db import dumps, iso, loads, utcnow
from .lifecycle import Candidate, select_candidates
from .nlp.normalize import clean_display, normalize, tokens
from .providers import ProviderError, chat_provider
from .providers.base import ChatRequest
from .sources import Registry

log = logging.getLogger(__name__)

PROMPT_VERSION = "v1"


# --- output schema -----------------------------------------------------------------------
class Localized(BaseModel):
    en: str
    fa: str


class FactOut(BaseModel):
    id: str
    text: Localized
    kind: Literal["event", "statement", "claim", "figure"]
    attributed_to: str
    supporting: list[str]
    contradicting: list[str]


class Position(BaseModel):
    text: Localized
    articles: list[str]


class DisputeOut(BaseModel):
    topic: Localized
    positions: list[Position]


class StoryOut(BaseModel):
    title: Localized
    summary: Localized
    facts: list[FactOut]
    disputes: list[DisputeOut]
    impact: int


def _obj(props: dict) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


_STR = {"type": "string"}
_LOC = _obj({"en": _STR, "fa": _STR})
_REFS = {"type": "array", "items": _STR}

# Written out by hand (no $refs) so it works with every provider's structured-output mode.
OUTPUT_SCHEMA = _obj({
    "title": _LOC,
    "summary": _LOC,
    "facts": {"type": "array", "items": _obj({
        "id": _STR,
        "text": _LOC,
        "kind": {"type": "string", "enum": ["event", "statement", "claim", "figure"]},
        "attributed_to": _STR,
        "supporting": _REFS,
        "contradicting": _REFS,
    })},
    "disputes": {"type": "array", "items": _obj({
        "topic": _LOC,
        "positions": {"type": "array", "items": _obj({"text": _LOC, "articles": _REFS})},
    })},
    "impact": {"type": "integer"},
})


# --- prompts ------------------------------------------------------------------------------
class Prompts:
    def __init__(self, directory: Path | None = None):
        self.env = Environment(trim_blocks=True, lstrip_blocks=True, autoescape=False)
        self.dir = directory

    def _read(self, name: str) -> str:
        if self.dir:
            return (self.dir / name).read_text(encoding="utf-8")
        return resources.files("haqiqat.prompts").joinpath(name).read_text(encoding="utf-8")

    def system(self) -> str:
        return self._read(f"system.{PROMPT_VERSION}.md")

    def render(self, kind: str, **ctx) -> str:
        return self.env.from_string(self._read(f"{kind}.{PROMPT_VERSION}.md")).render(**ctx)


# --- style check ----------------------------------------------------------------------------
def style_flags(output: dict, banned: dict[str, list[str]]) -> list[str]:
    """Loaded terms that slipped into our own text (not quotes from sources)."""
    flags = []
    texts = [output["title"], output["summary"], *[f["text"] for f in output["facts"]]]
    for lang, terms in banned.items():
        body = " ".join(t.get(lang, "") for t in texts)
        toks = set(tokens(body))
        norm = normalize(body).lower()
        for term in terms:
            t = normalize(term).lower()
            if (" " in t and t in norm) or t in toks:
                flags.append(f"{lang}:{term}")
    return flags


# --- synthesis ------------------------------------------------------------------------------
@dataclass
class SynthStats:
    candidates: int = 0
    created: int = 0
    updated: int = 0
    skipped_budget: int = 0
    failed: int = 0
    spent_usd: float = 0.0
    errors: list[str] = field(default_factory=list)


def pick_articles(articles: list[ArticleInfo], limit: int) -> list[ArticleInfo]:
    """One article per independence group (earliest first), rotating across camps so the
    model sees every side before it sees a second article from any side."""
    first_by_group: dict[str, ArticleInfo] = {}
    for a in sorted(articles, key=lambda a: a.published_at):
        if not a.is_dup:
            first_by_group.setdefault(a.group, a)
    by_camp: dict[str, list[ArticleInfo]] = {}
    for a in first_by_group.values():
        by_camp.setdefault(a.camp, []).append(a)
    picked: list[ArticleInfo] = []
    while len(picked) < limit and any(by_camp.values()):
        for camp in sorted(by_camp):
            if by_camp[camp] and len(picked) < limit:
                picked.append(by_camp[camp].pop(0))
    return picked


class Synthesizer:
    def __init__(self, conn: sqlite3.Connection, cfg: Config, registry: Registry,
                 budget: Budget | None = None, prompts: Prompts | None = None,
                 banned_terms: dict[str, list[str]] | None = None):
        self.conn = conn
        self.cfg = cfg
        self.registry = registry
        self.budget = budget or Budget(conn, cfg)
        self.prompts = prompts or Prompts(cfg.path(cfg.prompts_dir) if cfg.prompts_dir else None)
        self.banned = banned_terms or {}

    def _stage(self, name: str):
        """Stage config; `update` falls back to `synthesize` when not configured."""
        return self.cfg.stages.get(name) or self.cfg.stages["synthesize"]

    def _article_payload(self, a: ArticleInfo, ref: str) -> dict:
        src = self.registry.get(a.source_id)
        own = src.ownership if src else None
        ownership = own.kind if own else "unknown"
        if own and own.state:
            ownership += f" ({own.state})"
        return {
            "ref": ref,
            "source": src.name.en if src else a.source_id,
            "ownership": ownership,
            "lang": a.lang,
            "published": iso(a.published_at),
            "title": clean_display(a.title),
            "lead": clean_display(lead_of(a.title, a.text, a.summary,
                                          self.cfg.lifecycle.lead_chars)),
        }

    def _source_names(self, ids: list[int], cov: Coverage) -> str:
        by_id = cov.by_id()
        names = []
        for i in ids:
            a = by_id.get(i)
            if a:
                src = self.registry.get(a.source_id)
                name = src.name.en if src else a.source_id
                if name not in names:
                    names.append(name)
        return ", ".join(names) or "—"

    def build_request(self, cand: Candidate) -> tuple[ChatRequest, dict[str, int], dict | None]:
        lc = self.cfg.lifecycle
        stage = "update" if cand.is_update else "synthesize"
        sc = self._stage(stage)
        previous = None
        if cand.is_update:
            arts = pick_articles(cand.new_articles, lc.max_articles_update)
            row = self.conn.execute(
                "SELECT version, output FROM syntheses WHERE story_id=? ORDER BY version DESC"
                " LIMIT 1", (cand.story_id,),
            ).fetchone()
            previous = loads(row["output"])
            previous["version"] = row["version"]
        else:
            arts = pick_articles(cand.coverage.articles, lc.max_articles_new)
        ref_map = {f"A{i + 1}": a.id for i, a in enumerate(arts)}
        payload_articles = [self._article_payload(a, f"A{i + 1}") for i, a in enumerate(arts)]
        ctx: dict = {"articles": payload_articles, "n_groups": cand.coverage.n_groups,
                     "mode": stage}
        if previous is not None:
            prev_view = {
                "version": previous["version"],
                "title": previous["title"],
                "summary": previous["summary"],
                "disputes": previous.get("disputes", []),
                "facts": [
                    {**f, "sources": self._source_names(f.get("supporting", []), cand.coverage)}
                    for f in previous.get("facts", [])
                ],
            }
            ctx["previous"] = prev_view
            ctx["next_fact_id"] = _next_fact_number(previous.get("facts", []))
        user = self.prompts.render(stage, **ctx)
        req = ChatRequest(
            system=self.prompts.system(), user=user, schema=OUTPUT_SCHEMA, schema_name="story",
            model=sc.model, max_tokens=sc.max_output_tokens, effort=sc.effort, context=ctx,
        )
        return req, ref_map, previous

    def run(self, now=None, max_calls: int | None = None) -> SynthStats:
        stats = SynthStats()
        cands = select_candidates(self.conn, self.cfg, self.registry, now)
        stats.candidates = len(cands)
        for cand in cands:
            if max_calls is not None and stats.created + stats.updated >= max_calls:
                break
            stage = "update" if cand.is_update else "synthesize"
            sc = self._stage(stage)
            req, ref_map, previous = self.build_request(cand)
            est = self.budget.estimate(sc.model, len(req.system) + len(req.user),
                                       sc.max_output_tokens)
            if est > self.budget.remaining():
                stats.skipped_budget += 1
                continue
            try:
                provider = chat_provider(self.cfg, sc.provider)
                res = provider.complete_json(req)
                out = StoryOut.model_validate(res.data).model_dump()
            except (ProviderError, ValidationError) as e:
                stats.failed += 1
                stats.errors.append(f"story {cand.story_id}: {e}")
                self.budget.record(stage=stage, provider=sc.provider, model=sc.model, ok=False,
                                   error=str(e)[:500])
                continue
            cost = chat_cost(self.cfg, sc.model, res)
            self.budget.record(stage=stage, provider=sc.provider, model=res.model,
                               input_tokens=res.input_tokens + res.cache_read_tokens
                               + res.cache_write_tokens,
                               output_tokens=res.output_tokens, cost=cost)
            stats.spent_usd += cost
            final = merge_output(out, ref_map, previous)
            final["style_flags"] = style_flags(final, self.banned)
            final["triggers"] = cand.triggers
            self._store(cand, final, sc.provider, res.model, sorted(ref_map.values()),
                        res.input_tokens + res.cache_read_tokens + res.cache_write_tokens,
                        res.output_tokens, cost)
            if cand.is_update:
                stats.updated += 1
            else:
                stats.created += 1
        return stats

    def _store(self, cand: Candidate, output: dict, provider: str, model: str,
               input_ids: list[int], in_tok: int, out_tok: int, cost: float) -> None:
        now = iso(utcnow())
        self.conn.execute(
            "INSERT INTO syntheses (story_id, version, created_at, trigger, provider, model,"
            " prompt_version, input_article_ids, output, input_tokens, output_tokens, cost_usd)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (cand.story_id, cand.version, now, ",".join(cand.triggers), provider, model,
             PROMPT_VERSION, dumps(input_ids), dumps(output), in_tok, out_tok, cost),
        )
        self.conn.execute(
            "UPDATE stories SET current_version=?, last_synth_at=?, last_synth_article_ids=?,"
            " last_synth_groups=? WHERE id=?",
            (cand.version, now, dumps(sorted(a.id for a in cand.coverage.articles)),
             dumps(sorted(cand.coverage.groups)), cand.story_id),
        )
        self.conn.commit()


def _next_fact_number(facts: list[dict]) -> int:
    nums = [int(f["id"][1:]) for f in facts if f["id"][1:].isdigit()]
    return max(nums, default=0) + 1


def _map_refs(refs: list[str], ref_map: dict[str, int]) -> list[int]:
    return sorted({ref_map[r.strip()] for r in refs if r.strip() in ref_map})


def merge_output(out: dict, ref_map: dict[str, int], previous: dict | None) -> dict:
    """Turn article references into article ids and merge an update into the previous
    version. New facts must cite at least one article; uncited facts are dropped."""
    prev_facts = {f["id"]: f for f in (previous or {}).get("facts", [])}
    facts: list[dict] = []
    seen: set[str] = set()
    next_num = max(_next_fact_number(list(prev_facts.values())), _next_fact_number(out["facts"]))
    for f in out["facts"]:
        sup = _map_refs(f["supporting"], ref_map)
        con = _map_refs(f["contradicting"], ref_map)
        old = prev_facts.get(f["id"])
        if old is not None and f["id"] not in seen:
            facts.append({
                **old,
                "text": f["text"],
                "supporting": sorted(set(old["supporting"]) | set(sup)),
                "contradicting": sorted(set(old.get("contradicting", [])) | set(con)),
            })
            seen.add(f["id"])
            continue
        if not sup:
            continue  # uncited: rejected
        fid = f["id"]
        if fid in seen or fid in prev_facts or not re.fullmatch(r"F\d+", fid):
            fid = f"F{next_num}"
            next_num += 1
        seen.add(fid)
        facts.append({
            "id": fid, "text": f["text"], "kind": f["kind"],
            "attributed_to": f["attributed_to"], "supporting": sup, "contradicting": con,
        })
    for fid, old in prev_facts.items():
        if fid not in seen:
            facts.append(old)
    disputes = list((previous or {}).get("disputes", []))
    for d in out["disputes"]:
        positions = [
            {"text": p["text"], "articles": _map_refs(p["articles"], ref_map)}
            for p in d["positions"]
        ]
        positions = [p for p in positions if p["articles"]]
        if len(positions) >= 1:
            disputes.append({"topic": d["topic"], "positions": positions})
    return {
        "title": out["title"],
        "summary": out["summary"],
        "facts": facts,
        "disputes": disputes,
        "impact": max(0, min(10, int(out["impact"]))),
    }
