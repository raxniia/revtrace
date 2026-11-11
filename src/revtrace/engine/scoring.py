from __future__ import annotations

from ..stats import strength
from .schema import Verdict

GAP_ALPHA = 0.01
SHIFT_ALPHA = 0.01
MIN_RELATIVE_GAP = 0.20
MIN_EXPLAINED = 0.10
WEIGHTS = {"gap": 0.35, "shift": 0.25, "attribution": 0.40}


def judge(test: dict | None) -> Verdict:
    if not test:
        return Verdict(label="inconclusive", confidence=0)
    gap, shift = test["gap"], test["shift"]
    relative_gap = gap["relative_gap"] or 0.0
    explained = test["explained_share"] or 0.0
    components = {
        "gap": round(strength(gap["p_value"]) * min(1.0, relative_gap / 0.3), 3),
        "shift": round(strength(shift["p_value"]), 3),
        "attribution": round(explained, 3),
    }
    confidence = round(100 * sum(WEIGHTS[k] * components[k] for k in WEIGHTS))
    moves_conversion = gap["p_value"] < GAP_ALPHA and relative_gap >= MIN_RELATIVE_GAP
    changed = shift["p_value"] < SHIFT_ALPHA and explained >= MIN_EXPLAINED
    label = "rejected" if not moves_conversion else "primary" if changed else "chronic"
    return Verdict(label=label, confidence=confidence, components=components)


def evidence_grade(confidence: int) -> str:
    return "strong" if confidence >= 70 else "moderate" if confidence >= 40 else "weak"
