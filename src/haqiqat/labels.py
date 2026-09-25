"""Fact labels and blindspots, computed by code from coverage, never by the LLM.

The LLM only reports which articles support or contradict each fact. Whether that adds
up to "confirmed" is a published rule applied here, using the independence groups and
camps from the source registry. Change the rule in config and every label follows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import LabelConfig
from .coverage import Coverage

CONFIRMED = "confirmed"
CORROBORATED = "corroborated"
ONE_SIDE = "one_side"
SINGLE_SOURCE = "single_source"
DISPUTED = "disputed"

# Strongest first; used for sorting facts on a page.
ORDER = [CONFIRMED, CORROBORATED, DISPUTED, ONE_SIDE, SINGLE_SOURCE]

LABEL_NAMES = {
    CONFIRMED: {"en": "Widely confirmed", "fa": "تأییدشده از چند سو"},
    CORROBORATED: {"en": "Confirmed across sides", "fa": "تأیید از دو سو"},
    ONE_SIDE: {"en": "Reported by one side", "fa": "فقط از یک سو"},
    SINGLE_SOURCE: {"en": "Single source", "fa": "تک‌منبع"},
    DISPUTED: {"en": "Disputed", "fa": "مورد اختلاف"},
}


@dataclass
class LabeledFact:
    id: str
    text: dict[str, str]
    kind: str
    attributed_to: str
    supporting: list[int]
    contradicting: list[int]
    label: str
    n_groups: int
    camps: list[str] = field(default_factory=list)


def label_fact(supporting: list[int], contradicting: list[int], cov: Coverage,
               lc: LabelConfig) -> tuple[str, int, list[str]]:
    by_id = cov.by_id()
    groups = {by_id[i].group for i in supporting if i in by_id}
    camps = sorted({cov.group_camp[g] for g in groups})
    against = [i for i in contradicting if i in by_id]
    if against:
        return DISPUTED, len(groups), camps
    if len(groups) >= lc.confirmed_min_groups and len(camps) >= lc.confirmed_min_camps:
        return CONFIRMED, len(groups), camps
    if len(groups) >= 2 and len(camps) >= 2:
        return CORROBORATED, len(groups), camps
    if len(groups) >= 2:
        return ONE_SIDE, len(groups), camps
    return SINGLE_SOURCE, len(groups), camps


def label_facts(facts: list[dict], cov: Coverage, lc: LabelConfig) -> list[LabeledFact]:
    out = []
    for f in facts:
        sup = [int(i) for i in f.get("supporting", [])]
        con = [int(i) for i in f.get("contradicting", [])]
        label, n, camps = label_fact(sup, con, cov, lc)
        out.append(LabeledFact(
            id=f["id"], text=f["text"], kind=f.get("kind", "event"),
            attributed_to=f.get("attributed_to") or "", supporting=sup, contradicting=con,
            label=label, n_groups=n, camps=camps,
        ))
    return sorted(out, key=lambda x: (ORDER.index(x.label), -x.n_groups))


def confirmation_share(facts: list[LabeledFact]) -> float:
    if not facts:
        return 0.0
    strong = sum(1 for f in facts if f.label in (CONFIRMED, CORROBORATED))
    return strong / len(facts)


def blindspot(cov: Coverage, lc: LabelConfig) -> str | None:
    """The camp that dominates coverage of a well-covered story, if one does."""
    if cov.n_groups < lc.blindspot_min_groups:
        return None
    camps = cov.camps()
    if not camps:
        return None
    top, n = camps.most_common(1)[0]
    return top if n / cov.n_groups >= lc.blindspot_share else None
