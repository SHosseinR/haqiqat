"""End-to-end, offline: mock web + fake embeddings + fake LLM."""

import json

from conftest import FEEDS_ROUND_2, FakeWeb, make_app
from haqiqat.db import loads
from haqiqat.lifecycle import NEW_GROUPS, select_candidates


def story_of(app, source_id, slug):
    return app.conn.execute(
        "SELECT story_id, dup_of FROM articles WHERE url = ?",
        (f"https://{source_id}.test/{slug}",),
    ).fetchone()


def test_full_pipeline(app_factory, project):
    app = app_factory()
    ing = app.ingest()
    assert ing.feeds_ok == 6 and ing.new_articles == 7 and ing.texts_extracted == 7

    stats = app.process()
    assert stats.duplicates == 1

    drone = story_of(app, "state", "drone")["story_id"]
    # English and Persian reports of the same event share a story...
    assert story_of(app, "wire", "drone")["story_id"] == drone
    assert story_of(app, "abroad", "drone")["story_id"] == drone
    # ...the verbatim copy is marked as a duplicate of the original, in the same story...
    copy = story_of(app, "copyco", "drone-copy")
    assert copy["story_id"] == drone and copy["dup_of"] is not None
    # ...and a different event does not.
    assert story_of(app, "wire", "quake")["story_id"] != drone
    assert story_of(app, "regional", "quake")["story_id"] == story_of(app, "wire", "quake")[
        "story_id"]

    row = app.conn.execute("SELECT * FROM stories WHERE id=?", (drone,)).fetchone()
    assert loads(row["countries"]) == ["IR"]
    assert "iran" in loads(row["regions"])
    assert loads(row["score_parts"])["n_groups"] == 3  # the copy adds no group

    # Single-source story is not a synthesis candidate; the two mature stories are.
    syn = app.synthesize()
    assert syn.created == 2 and syn.failed == 0
    out = json.loads(app.conn.execute(
        "SELECT output FROM syntheses WHERE story_id=?", (drone,)).fetchone()["output"])
    assert all(f["supporting"] for f in out["facts"])  # every fact cites articles
    assert app.budget.spent_today() > 0

    counts = app.build_site()
    site = project / "build" / "site"
    assert counts["stories"] == 2
    for rel in ("index.html", "fa/index.html", "en/index.html", f"fa/story/{drone}/index.html",
                "en/region/iran/index.html", "fa/sources/index.html", "api/stories.json",
                "fa/feed.xml", "assets/style.css"):
        assert (site / rel).exists(), rel
    fa_story = (site / "fa" / "story" / str(drone) / "index.html").read_text(encoding="utf-8")
    assert 'dir="rtl"' in fa_story and "تأییدشده" in fa_story
    api = json.loads((site / "api" / "stories.json").read_text(encoding="utf-8"))
    assert {s["id"] for s in api["stories"]} >= {drone}

    tg = app.publish_telegram(dry_run=True)
    assert tg.posted == 4  # 2 stories x 2 channels
    assert any("haqiqat.test/fa/story/" in p for p in tg.previews)


def test_update_sends_only_new_articles(project):
    app = make_app(project, FakeWeb(FEEDS_ROUND_2 | {"reform": FEEDS_ROUND_2["reform"][:1]}))
    app.ingest()
    app.process()
    app.synthesize()
    drone = story_of(app, "state", "drone")["story_id"]
    v1 = app.conn.execute("SELECT * FROM syntheses WHERE story_id=?", (drone,)).fetchone()

    # Nothing new: no candidates.
    assert [c for c in select_candidates(app.conn, app.cfg, app.registry)
            if c.story_id == drone] == []

    # A new independent group reports the event.
    app2 = make_app(project, FakeWeb(FEEDS_ROUND_2))
    app2.ingest()
    app2.process()
    new_article = story_of(app2, "reform", "drone2")
    assert new_article["story_id"] == drone
    cands = [c for c in select_candidates(app2.conn, app2.cfg, app2.registry)
             if c.story_id == drone]
    assert cands and NEW_GROUPS in cands[0].triggers and cands[0].version == 2

    app2.synthesize()
    v2 = app2.conn.execute(
        "SELECT * FROM syntheses WHERE story_id=? AND version=2", (drone,)).fetchone()
    assert v2 is not None
    new_id = app2.conn.execute(
        "SELECT id FROM articles WHERE url='https://reform.test/drone2'").fetchone()["id"]
    assert loads(v2["input_article_ids"]) == [new_id]  # only the new article was sent
    f1_v1 = loads(v1["output"])["facts"][0]
    f1_v2 = next(f for f in loads(v2["output"])["facts"] if f["id"] == f1_v1["id"])
    assert set(f1_v2["supporting"]) == set(f1_v1["supporting"]) | {new_id}


def test_budget_cap_skips_llm(project):
    app = make_app(project, FakeWeb(FEEDS_ROUND_2))
    app.cfg.budget.daily_usd = 0.0
    app.ingest()
    app.process()
    syn = app.synthesize()
    assert syn.created == 0 and syn.skipped_budget == 2
    app.build_site()  # stories still publish, with the extractive / headline fallback
    api = json.loads((project / "build/site/api/stories.json").read_text(encoding="utf-8"))
    assert api["stories"] and all(s["kind"] in ("extractive", "headlines")
                                  for s in api["stories"])
