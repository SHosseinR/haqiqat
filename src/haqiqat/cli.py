"""Command line: `haqiqat <command>`. Run `haqiqat --help` for the list."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from .config import load_config, with_fake_providers
from .pipeline import App, default_config_path


def _app(args) -> App:
    cfg = load_config(args.config or default_config_path())
    fake_llm = getattr(args, "llm", None) == "fake"
    fake_emb = getattr(args, "embeddings", None) == "fake"
    if fake_llm or fake_emb:
        cfg = with_fake_providers(cfg, llm=fake_llm, embeddings=fake_emb)
    if getattr(args, "db", None):
        cfg.database = args.db
    return App(cfg)


def _print(obj) -> None:
    if hasattr(obj, "__dataclass_fields__"):
        obj = asdict(obj)
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_validate_sources(args) -> int:
    from .sources import RegistryError

    app = _app(args)
    try:
        reg = app.registry
    except RegistryError as e:
        print(e, file=sys.stderr)
        return 1
    feeds = sum(len(s.feeds) for s in reg.sources.values())
    print(f"{len(reg.sources)} sources, {feeds} feeds: schema OK")
    if not args.probe:
        return 0
    from .db import utcnow
    from .ingest import Fetcher, parse_rss, parse_sitemap

    fetcher = Fetcher(app.cfg)
    failed = 0
    for src in reg.sources.values():
        for feed in src.feeds:
            try:
                r = fetcher.get(feed.url)
                r.raise_for_status()
                if feed.kind == "rss":
                    n = len(parse_rss(r.content, utcnow()))
                else:
                    items, children = parse_sitemap(r.content, utcnow())
                    n = len(items) or len(children)
                status = "OK " if n else "EMPTY"
                failed += 0 if n else 1
            except Exception as e:  # report every feed, keep going
                status, n = "FAIL", 0
                failed += 1
                print(f"FAIL  {src.id:28} {feed.url}  ({e})")
                continue
            print(f"{status} {src.id:28} {n:4} items  {feed.url}")
    print(f"{failed} feeds need attention")
    return 1 if failed else 0


def cmd_export_schema(args) -> int:
    from .sources import source_json_schema

    out = Path(args.out)
    out.write_text(json.dumps(source_json_schema(), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out}")
    return 0


def cmd_ingest(args) -> int:
    _print(_app(args).ingest(args.limit_sources, args.source))
    return 0


def cmd_process(args) -> int:
    _print(_app(args).process())
    return 0


def cmd_synthesize(args) -> int:
    _print(_app(args).synthesize(args.max_calls))
    return 0


def cmd_build_site(args) -> int:
    _print(_app(args).build_site())
    return 0


def cmd_publish_telegram(args) -> int:
    stats = _app(args).publish_telegram(dry_run=args.dry_run)
    for p in stats.previews:
        print(p, end="\n\n")
    print(f"posted={stats.posted} edited={stats.edited} digests={stats.digests}")
    return 0


def cmd_run(args) -> int:
    app = _app(args)
    report: dict = {}
    if not args.skip_ingest:
        report["ingest"] = asdict(app.ingest(args.limit_sources, args.source))
    report["process"] = asdict(app.process())
    report["synthesize"] = asdict(app.synthesize(args.max_calls))
    report["site"] = app.build_site()
    if app.cfg.telegram.enabled or args.telegram_dry_run:
        tg = app.publish_telegram(dry_run=args.telegram_dry_run)
        report["telegram"] = {"posted": tg.posted, "edited": tg.edited, "digests": tg.digests}
    report["spent_today_usd"] = round(app.budget.spent_today(), 4)
    _print(report)
    return 0


def cmd_costs(args) -> int:
    app = _app(args)
    rows = app.conn.execute(
        "SELECT day, stage, model, COUNT(*) AS calls, SUM(input_tokens) AS input_tokens,"
        " SUM(output_tokens) AS output_tokens, ROUND(SUM(cost_usd), 4) AS usd,"
        " SUM(1 - ok) AS failures FROM llm_usage GROUP BY day, stage, model"
        " ORDER BY day DESC, usd DESC LIMIT ?", (args.limit,),
    ).fetchall()
    _print([dict(r) for r in rows])
    print(f"today: ${app.budget.spent_today():.4f} of ${app.cfg.budget.daily_usd:.2f}")
    return 0


def cmd_eval_embeddings(args) -> int:
    from .evaluate import evaluate_pairs

    app = _app(args)
    _print(evaluate_pairs(app.embedder, Path(args.pairs), app.cfg.clustering.join_threshold))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="haqiqat", description=__doc__)
    p.add_argument("-c", "--config", help="config file (default: config/config.yaml, "
                   "falling back to config/config.example.yaml)")
    p.add_argument("--db", help="override the database path")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    def providers(sp):
        sp.add_argument("--llm", choices=["config", "fake"], default="config",
                        help="'fake' runs offline without any API")
        sp.add_argument("--embeddings", choices=["config", "fake"], default="config")

    sp = add("validate-sources", cmd_validate_sources,
             "check source files (and feeds with --probe)")
    sp.add_argument("--probe", action="store_true", help="fetch every feed and report")
    sp = add("export-schema", cmd_export_schema, "write the JSON schema for source files")
    sp.add_argument("--out", default="sources/schema.json")
    sp = add("ingest", cmd_ingest, "fetch new articles")
    sp.add_argument("--limit-sources", type=int)
    sp.add_argument("--source", action="append", help="only this source id (repeatable)")
    sp = add("process", cmd_process, "dedup, embed, cluster and rank")
    providers(sp)
    sp = add("synthesize", cmd_synthesize, "LLM summaries for stories that need one")
    providers(sp)
    sp.add_argument("--max-calls", type=int)
    add("build-site", cmd_build_site, "generate the static site")
    sp = add("publish-telegram", cmd_publish_telegram, "post to Telegram channels")
    sp.add_argument("--dry-run", action="store_true", help="print posts instead of sending")
    sp = add("run", cmd_run, "ingest, process, synthesize, build site, publish")
    providers(sp)
    sp.add_argument("--once", action="store_true",
                    help="accepted for cron clarity; always one pass")
    sp.add_argument("--limit-sources", type=int)
    sp.add_argument("--source", action="append")
    sp.add_argument("--skip-ingest", action="store_true")
    sp.add_argument("--max-calls", type=int)
    sp.add_argument("--telegram-dry-run", action="store_true")
    sp = add("costs", cmd_costs, "show model spend by day, stage and model")
    sp.add_argument("--limit", type=int, default=30)
    sp = add("eval-embeddings", cmd_eval_embeddings,
             "check an embeddings provider on same-event / different-event pairs")
    providers(sp)
    sp.add_argument("--pairs", default="tests/data/pairs.yaml")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
