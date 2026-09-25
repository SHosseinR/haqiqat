"""Runtime configuration, loaded from a YAML file (see config/config.example.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

ProviderKind = Literal["openai_compat", "anthropic", "local", "fake"]


class ProviderConfig(BaseModel):
    kind: ProviderKind
    base_url: str | None = None
    api_key_env: str | None = None
    timeout: float = 120.0
    # openai_compat only: how to ask for JSON. "json_schema" (strict schema), "json_object"
    # (any JSON; we validate afterwards) or "none" (instructions only).
    json_mode: Literal["json_schema", "json_object", "none"] = "json_schema"
    # openai_compat only: some models want "max_completion_tokens" instead.
    max_tokens_field: str = "max_tokens"
    # anthropic only: opt into server-side refusal fallbacks ("default" routes by category).
    fallbacks: str | None = None


class StageConfig(BaseModel):
    provider: str
    model: str
    max_output_tokens: int = 4000
    effort: str | None = None  # anthropic: low | medium | high | xhigh | max


class EmbeddingConfig(BaseModel):
    provider: str
    model: str
    dimensions: int | None = None
    batch_size: int = 64
    max_chars: int = 2000


class Price(BaseModel):
    input: float = 0.0  # USD per 1M tokens
    output: float = 0.0
    cache_read: float | None = None


class BudgetConfig(BaseModel):
    daily_usd: float = 2.0
    # Price used when a model is missing from `pricing`, so unknown models are never "free".
    default_price: Price = Price(input=5.0, output=25.0)


class HttpConfig(BaseModel):
    user_agent: str = "HaqiqatBot/0.1 (+https://github.com/SHosseinR/haqiqat)"
    timeout: float = 20.0
    per_host_delay: float = 1.0
    max_items_per_feed: int = 40
    fetch_full_text: bool = True
    max_full_text_per_run: int = 400
    lookback_hours: int = 48


class ClusteringConfig(BaseModel):
    window_hours: int = 72
    join_threshold: float = 0.62
    # Above this similarity an article joins even without a shared place or entity.
    strong_threshold: float = 0.75
    merge_threshold: float = 0.80
    storyline_threshold: float = 0.55
    storyline_window_days: int = 30
    near_duplicate_jaccard: float = 0.7


class LifecycleConfig(BaseModel):
    min_groups_for_synthesis: int = 2
    top_k_candidates: int = 50
    fast_track_groups: int = 3
    fast_track_hours: float = 1.0
    growth_ratio: float = 1.5
    novelty_threshold: float = 0.55
    top_n_for_short_debounce: int = 15
    debounce_hours_top: float = 2.0
    debounce_hours_other: float = 12.0
    max_versions_per_day: int = 4
    max_articles_new: int = 8
    max_articles_update: int = 6
    lead_chars: int = 1200


class LabelConfig(BaseModel):
    confirmed_min_groups: int = 3
    confirmed_min_camps: int = 2
    blindspot_min_groups: int = 4
    blindspot_share: float = 0.8


class RankingWeights(BaseModel):
    groups: float = 1.0
    lens_diversity: float = 0.8
    geo_scope: float = 0.3
    velocity: float = 0.5
    impact: float = 0.6
    confirmation: float = 0.3


class RankingConfig(BaseModel):
    weights: RankingWeights = RankingWeights()
    half_life_hours: float = 18.0
    velocity_window_hours: float = 6.0


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    channels: dict[str, str] = Field(default_factory=dict)  # lang -> "@channel" or chat id
    min_score: float = 2.0
    max_posts_per_day: int = 12
    digest_hour_local: int = 20
    digest_size: int = 10
    timezone: str = "Asia/Tehran"
    edit_window_hours: float = 48.0


class SiteConfig(BaseModel):
    title: dict[str, str] = Field(default_factory=lambda: {"en": "Haqiqat", "fa": "حقیقت"})
    base_url: str = "http://localhost:8000"
    output_dir: str = "build/site"
    languages: list[str] = Field(default_factory=lambda: ["en", "fa"])
    stories_per_page: int = 40
    source_repo_url: str = "https://github.com/SHosseinR/haqiqat"
    timezone: str = "Asia/Tehran"


class Config(BaseModel):
    database: str = "data/haqiqat.db"
    sources_dir: str = "sources"
    lenses_file: str = "config/lenses.yaml"
    regions_file: str = "config/regions.yaml"
    taxonomy_file: str = "config/taxonomy.yaml"
    gazetteer_file: str = "config/gazetteer.yaml"
    prompts_dir: str | None = None  # default: bundled prompts

    http: HttpConfig = HttpConfig()
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    embeddings: EmbeddingConfig
    stages: dict[str, StageConfig] = Field(default_factory=dict)  # synthesize, update
    pricing: dict[str, Price] = Field(default_factory=dict)
    budget: BudgetConfig = BudgetConfig()
    clustering: ClusteringConfig = ClusteringConfig()
    lifecycle: LifecycleConfig = LifecycleConfig()
    labels: LabelConfig = LabelConfig()
    ranking: RankingConfig = RankingConfig()
    telegram: TelegramConfig = TelegramConfig()
    site: SiteConfig = SiteConfig()

    # Directory the config file lives in; relative paths resolve against the repo root
    # (the config file's parent's parent when it lives in config/).
    root: Path = Path(".")

    def path(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else self.root / p

    def price(self, model: str) -> Price:
        return self.pricing.get(model, self.budget.default_price)


def load_config(path: str | Path) -> Config:
    path = Path(path).resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    root = path.parent.parent if path.parent.name == "config" else path.parent
    data["root"] = root
    return Config.model_validate(data)


def with_fake_providers(cfg: Config, llm: bool = True, embeddings: bool = True) -> Config:
    """Return a copy of the config wired to the offline fake providers (tests, dry runs)."""
    cfg = cfg.model_copy(deep=True)
    cfg.providers["fake"] = ProviderConfig(kind="fake")
    # Small non-zero price so budget accounting is exercised in dry runs and tests.
    cfg.pricing.setdefault("fake-llm", Price(input=1.0, output=5.0))
    if llm:
        for name, stage in cfg.stages.items():
            cfg.stages[name] = stage.model_copy(update={"provider": "fake", "model": "fake-llm"})
        for name in ("synthesize", "update"):
            cfg.stages.setdefault(name, StageConfig(provider="fake", model="fake-llm"))
    if embeddings:
        cfg.embeddings = cfg.embeddings.model_copy(
            update={"provider": "fake", "model": "fake-embed", "dimensions": 256}
        )
    return cfg
