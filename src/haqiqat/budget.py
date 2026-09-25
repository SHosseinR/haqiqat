"""Spend tracking and the hard daily cap. Every model call is recorded in `llm_usage`."""

from __future__ import annotations

import sqlite3

from .config import Config
from .db import iso, utcnow
from .providers.base import ChatResult


def cost_usd(cfg: Config, model: str, *, input_tokens: int = 0, output_tokens: int = 0,
             cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> float:
    p = cfg.price(model)
    cache_read_price = p.cache_read if p.cache_read is not None else p.input * 0.1
    return (
        input_tokens * p.input
        + cache_write_tokens * p.input * 1.25
        + cache_read_tokens * cache_read_price
        + output_tokens * p.output
    ) / 1_000_000


def chat_cost(cfg: Config, model: str, r: ChatResult) -> float:
    return cost_usd(
        cfg,
        model,
        input_tokens=r.input_tokens,
        output_tokens=r.output_tokens,
        cache_read_tokens=r.cache_read_tokens,
        cache_write_tokens=r.cache_write_tokens,
    )


class Budget:
    def __init__(self, conn: sqlite3.Connection, cfg: Config):
        self.conn = conn
        self.cfg = cfg

    def spent_today(self) -> float:
        day = utcnow().strftime("%Y-%m-%d")
        row = self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_usage WHERE day = ?", (day,)
        ).fetchone()
        return float(row[0])

    def remaining(self) -> float:
        return max(0.0, self.cfg.budget.daily_usd - self.spent_today())

    def estimate(self, model: str, prompt_chars: int, max_output_tokens: int) -> float:
        # Persian tokenizes to more tokens per character than English; 2.5 chars/token is a
        # conservative average for mixed input. Assume output uses half the allowance.
        return cost_usd(
            self.cfg,
            model,
            input_tokens=int(prompt_chars / 2.5),
            output_tokens=max_output_tokens // 2,
        )

    def record(self, *, stage: str, provider: str, model: str, input_tokens: int = 0,
               output_tokens: int = 0, cost: float = 0.0, ok: bool = True,
               error: str | None = None) -> None:
        now = utcnow()
        self.conn.execute(
            "INSERT INTO llm_usage (ts, day, stage, provider, model, input_tokens, output_tokens,"
            " cost_usd, ok, error) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (iso(now), now.strftime("%Y-%m-%d"), stage, provider, model, input_tokens,
             output_tokens, cost, int(ok), error),
        )
        self.conn.commit()
