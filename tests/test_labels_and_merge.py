from datetime import UTC, datetime

from haqiqat.config import LabelConfig
from haqiqat.coverage import ArticleInfo, Coverage
from haqiqat.labels import (
    CONFIRMED,
    CORROBORATED,
    DISPUTED,
    ONE_SIDE,
    SINGLE_SOURCE,
    blindspot,
    label_fact,
)
from haqiqat.synthesize import OUTPUT_SCHEMA, merge_output, pick_articles, style_flags

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def art(id, group, camp, dup=False, lang="en"):
    return ArticleInfo(id=id, source_id=group, group=group, camp=camp, lang=lang,
                       title=f"t{id}", url=f"https://x.test/{id}", published_at=T0,
                       is_dup=dup, summary="", text=None)


def coverage(arts):
    cov = Coverage(articles=arts, countries={"IR"})
    for a in arts:
        cov.groups.setdefault(a.group, a.published_at)
        cov.group_camp.setdefault(a.group, a.camp)
    return cov


COV = coverage([
    art(1, "irna", "iran:inside"),
    art(2, "tasnim", "iran:inside"),
    art(3, "bbc", "iran:outside"),
    art(4, "reuters", "origin:western"),
    art(5, "irna", "iran:inside", dup=True),
])
LC = LabelConfig()


def test_label_rules():
    assert label_fact([1, 3, 4], [], COV, LC)[0] == CONFIRMED
    assert label_fact([1, 3], [], COV, LC)[0] == CORROBORATED
    assert label_fact([1, 2], [], COV, LC)[0] == ONE_SIDE
    assert label_fact([1], [], COV, LC)[0] == SINGLE_SOURCE
    assert label_fact([1, 3, 4], [2], COV, LC)[0] == DISPUTED


def test_copies_do_not_count_as_independent():
    # Article 5 is a copy of IRNA: IRNA + its copy is still one group.
    label, n_groups, _ = label_fact([1, 5], [], COV, LC)
    assert (label, n_groups) == (SINGLE_SOURCE, 1)


def test_blindspot():
    one_sided = coverage([art(i, f"g{i}", "iran:inside") for i in range(5)])
    assert blindspot(one_sided, LC) == "iran:inside"
    assert blindspot(COV, LC) is None  # too few groups / balanced


def test_pick_articles_rotates_camps_and_skips_copies():
    picked = pick_articles(COV.articles, 3)
    assert [a.id for a in picked] == [1, 3, 4]
    assert all(not a.is_dup for a in pick_articles(COV.articles, 10))


def loc(s):
    return {"en": s, "fa": s}


def test_merge_new_maps_refs_and_drops_uncited_facts():
    out = {
        "title": loc("T"), "summary": loc("S"), "impact": 14,
        "facts": [
            {"id": "F1", "text": loc("a"), "kind": "event", "attributed_to": "",
             "supporting": ["A1", "A2"], "contradicting": ["A9"]},
            {"id": "F2", "text": loc("uncited"), "kind": "claim", "attributed_to": "X",
             "supporting": [], "contradicting": []},
            {"id": "F1", "text": loc("dup id"), "kind": "figure", "attributed_to": "Y",
             "supporting": ["A2"], "contradicting": []},
        ],
        "disputes": [{"topic": loc("toll"), "positions": [
            {"text": loc("12"), "articles": ["A1"]}, {"text": loc("31"), "articles": ["A2"]}]}],
    }
    merged = merge_output(out, {"A1": 101, "A2": 102}, None)
    assert merged["impact"] == 10
    # The uncited F2 is dropped; the duplicated id is renumbered past every id the model used.
    assert [f["id"] for f in merged["facts"]] == ["F1", "F3"]
    assert merged["facts"][0]["supporting"] == [101, 102]
    assert merged["facts"][0]["contradicting"] == []  # unknown ref dropped
    assert merged["facts"][1]["text"]["en"] == "dup id"
    assert merged["disputes"][0]["positions"][1]["articles"] == [102]


def test_merge_update_adds_support_and_keeps_omitted_facts():
    previous = {
        "title": loc("T"), "summary": loc("S"), "impact": 5, "disputes": [],
        "facts": [
            {"id": "F1", "text": loc("a"), "kind": "event", "attributed_to": "",
             "supporting": [1], "contradicting": []},
            {"id": "F2", "text": loc("b"), "kind": "claim", "attributed_to": "X",
             "supporting": [2], "contradicting": []},
        ],
    }
    out = {
        "title": loc("T2"), "summary": loc("S2"), "impact": 6, "disputes": [],
        "facts": [
            {"id": "F1", "text": loc("a (revised)"), "kind": "event", "attributed_to": "",
             "supporting": ["A1"], "contradicting": []},
            {"id": "F7", "text": loc("new"), "kind": "event", "attributed_to": "",
             "supporting": ["A2"], "contradicting": []},
        ],
    }
    merged = merge_output(out, {"A1": 10, "A2": 11}, previous)
    facts = {f["id"]: f for f in merged["facts"]}
    assert facts["F1"]["supporting"] == [1, 10]
    assert facts["F1"]["text"]["en"] == "a (revised)"
    assert facts["F2"]["supporting"] == [2]  # omitted: carried over unchanged
    assert set(facts) == {"F1", "F2", "F7"}
    assert facts["F7"]["supporting"] == [11]


def test_output_schema_is_strict_everywhere():
    def walk(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for child in node["properties"].values():
                walk(child)
        if node.get("type") == "array":
            walk(node["items"])

    walk(OUTPUT_SCHEMA)


def test_style_flags():
    out = {"title": {"en": "The regime said", "fa": "حکومت گفت"},
           "summary": {"en": "ok", "fa": "رژیم صهیونیستی"}, "facts": []}
    flags = style_flags(out, {"en": ["regime", "martyr"], "fa": ["رژیم صهیونیستی"]})
    assert flags == ["en:regime", "fa:رژیم صهیونیستی"]
