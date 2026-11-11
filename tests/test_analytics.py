from __future__ import annotations

import pytest

from revtrace import analytics
from revtrace.dataset import Dataset, DatasetError
from revtrace.engine.scoring import judge
from revtrace.stats import two_proportion_p

from .conftest import BASELINE, CURRENT


def test_two_proportion_p_is_symmetric_and_bounded():
    assert two_proportion_p(10, 100, 10, 100) == pytest.approx(1.0)
    assert two_proportion_p(5, 100, 30, 100) == pytest.approx(two_proportion_p(30, 100, 5, 100))
    assert two_proportion_p(5, 100, 30, 100) < 0.001


def test_conversion_drop_is_detected(ctx):
    comparison = analytics.compare_periods(ctx.ds, CURRENT, BASELINE)
    assert comparison["conversion_change_points"] < -3
    assert comparison["p_value"] < 0.001


def test_mix_and_segment_shares_are_consistent(ctx):
    test = analytics.factor_test(ctx.ds, "response_time", CURRENT, BASELINE)
    assert sum(s["current_share"] for s in test["segments"]) == pytest.approx(1, abs=1e-3)
    assert sum(s["contribution_points"] for s in test["segments"]) == pytest.approx(
        test["mix_effect_points"], abs=0.02
    )


@pytest.mark.parametrize(
    ("dimension", "expected"),
    [
        ("response_time", "primary"),
        ("followups", "primary"),
        ("product", "chronic"),
        ("price_band", "rejected"),
        ("wilaya", "rejected"),
    ],
)
def test_verdicts_match_planted_causes(ctx, dimension, expected):
    assert judge(analytics.factor_test(ctx.ds, dimension, CURRENT, BASELINE)).label == expected


def test_changepoint_lands_near_the_shock(ctx):
    changepoint = analytics.detect_changepoint(ctx.ds)
    assert changepoint and "2026-09-24" <= changepoint["date"] <= "2026-10-07"


def test_price_is_mentioned_by_buyers_too(ctx):
    themes = {t["theme"]: t for t in analytics.conversation_themes(ctx.ds)["themes"]}
    assert themes["price"]["lift"] < 1.5
    assert themes["slow_response"]["lift"] > 1.5


def test_search_uses_phrases_not_substrings_of_single_words(ctx):
    found = analytics.search_conversations(ctx.ds, "semaines bezzaf, trop long", status="lost")
    assert found["matches"] > 50
    assert all(
        "semaines bezzaf" in e["quote"].lower() or "trop long" in e["quote"].lower()
        for e in found["examples"]
    )


def test_dataset_rejects_missing_columns(tmp_path):
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "leads.csv").write_text("lead_id,created_at\nL1,2026-01-01\n")
    with pytest.raises(DatasetError, match="status"):
        Dataset(folder)


def test_model_card_and_counterfactual(ctx):
    assert ctx.model.card["trained"] and ctx.model.card["cv_auc"] > 0.62
    restored = ctx.model.counterfactual("response_time", CURRENT, BASELINE)
    assert restored["recoverable_points"] > 1
