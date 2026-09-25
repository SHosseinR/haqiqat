"""Wiring: load everything once, then run the stages in order."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import yaml

from .budget import Budget
from .cluster import Clusterer
from .config import Config
from .db import connect
from .embed import Embedder
from .ingest import Fetcher, Ingestor
from .nlp.classify import Taxonomy, TopicClassifier, load_taxonomy
from .nlp.geo import Gazetteer, Regions, load_regions
from .rank import rank_stories
from .sources import Registry, load_registry
from .synthesize import Synthesizer

log = logging.getLogger(__name__)


@dataclass
class App:
    cfg: Config
    # Injected in tests (mock HTTP transport); built from config otherwise.
    fetcher: Fetcher | None = None
    conn: sqlite3.Connection = field(init=False)

    def __post_init__(self):
        self.conn = connect(self.cfg.path(self.cfg.database))

    @cached_property
    def registry(self) -> Registry:
        return load_registry(self.cfg.path(self.cfg.sources_dir),
                             self.cfg.path(self.cfg.lenses_file))

    @cached_property
    def regions(self) -> Regions:
        return load_regions(self.cfg.path(self.cfg.regions_file))

    @cached_property
    def gazetteer(self) -> Gazetteer:
        return Gazetteer.load(self.cfg.path(self.cfg.gazetteer_file))

    @cached_property
    def taxonomy(self) -> Taxonomy:
        return load_taxonomy(self.cfg.path(self.cfg.taxonomy_file))

    @cached_property
    def budget(self) -> Budget:
        return Budget(self.conn, self.cfg)

    @cached_property
    def embedder(self) -> Embedder:
        return Embedder(self.conn, self.cfg, self.budget)

    @cached_property
    def classifier(self) -> TopicClassifier:
        texts = [f"{t.name['en']}. {t.name.get('fa', '')}. {t.description}"
                 for t in self.taxonomy.topics]
        return TopicClassifier(self.taxonomy, self.embedder.embed(texts))

    @cached_property
    def banned_terms(self) -> dict[str, list[str]]:
        path = self.cfg.path("config/style.yaml")
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {lang: [e["term"] for e in entries] for lang, entries in
                (data.get("avoid") or {}).items()}

    def ingest(self, limit_sources: int | None = None, source_ids: list[str] | None = None):
        ingestor = Ingestor(self.conn, self.cfg, self.registry, fetcher=self.fetcher)
        return ingestor.run(limit_sources, source_ids)

    def process(self):
        clusterer = Clusterer(self.conn, self.cfg, self.registry, self.embedder,
                              self.gazetteer, self.regions, self.classifier)
        stats = clusterer.process()
        rank_stories(self.conn, self.cfg, self.registry)
        return stats

    def synthesize(self, max_calls: int | None = None):
        synth = Synthesizer(self.conn, self.cfg, self.registry, self.budget,
                            banned_terms=self.banned_terms)
        stats = synth.run(max_calls=max_calls)
        rank_stories(self.conn, self.cfg, self.registry)  # impact/confirmation changed
        return stats

    def build_site(self):
        from .publish.site import SiteBuilder

        return SiteBuilder(self.conn, self.cfg, self.registry, self.regions, self.gazetteer,
                           self.taxonomy).build()

    def publish_telegram(self, dry_run: bool = False):
        import os

        from .publish.telegram import TelegramAPI, TelegramPublisher

        api = None
        if not dry_run:
            token = os.environ.get(self.cfg.telegram.bot_token_env)
            if not token:
                raise SystemExit(f"{self.cfg.telegram.bot_token_env} is not set")
            api = TelegramAPI(token)
        return TelegramPublisher(self.conn, self.cfg, self.registry, api, dry_run).run()


def default_config_path() -> Path:
    for candidate in (Path("config/config.yaml"), Path("config/config.example.yaml")):
        if candidate.exists():
            return candidate
    return Path("config/config.yaml")
