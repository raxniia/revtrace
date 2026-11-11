from __future__ import annotations

from datetime import datetime

from .. import analytics
from ..dataset import Dataset
from .schema import Evidence, Impact

MIN_POLICY_SCORE = 0.15
CLAIMED_THEME = {"price_band": "price", "response_time": "slow_response", "sales_rep": "slow_response"}


def pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def month_name(month: str) -> str:
    return datetime.strptime(month, "%Y-%m").strftime("%B %Y")


def money(value: float, currency: str) -> str:
    return f"{value:,.0f} {currency}".replace(",", " ").strip()


def is_concentrated(theme: dict) -> bool:
    return (
        theme["p_value"] < 0.01
        and theme["rate_in_segment"] >= 0.2
        and theme["rate_in_segment"] >= 2 * theme["rate_elsewhere"]
    )


def factor_evidence(test: dict) -> list[Evidence]:
    gap, shift = test["gap"], test["shift"]
    label = test["label"]
    current, baseline = month_name(test["current"]), month_name(test["baseline"])
    items: list[Evidence] = []
    significant = gap["p_value"] < 0.01 and (gap["relative_gap"] or 0) >= 0.2
    if significant:
        items.append(
            Evidence(
                kind="metric",
                direction="supports",
                source="test_factor",
                text=(
                    f"By {label}, “{gap['worst']}” converts at **{pct(gap['worst_rate'])}** "
                    f"against **{pct(gap['best_rate'])}** for “{gap['best']}”."
                ),
            )
        )
    else:
        items.append(
            Evidence(
                kind="metric",
                direction="contradicts",
                source="test_factor",
                text=(
                    f"Conversion barely moves with {label}: from **{pct(gap['worst_rate'])}** "
                    f"to **{pct(gap['best_rate'])}** across segments, a gap that chance alone "
                    f"would produce (p = {gap['p_value']:.2f})."
                ),
            )
        )
    moved = shift["p_value"] < 0.01
    if moved:
        items.append(
            Evidence(
                kind="metric",
                direction="supports" if significant else "context",
                source="test_factor",
                text=(
                    f"The share of leads in “{shift['culprit']}” went from "
                    f"**{pct(shift['culprit_baseline_share'], 0)}** in {baseline} to "
                    f"**{pct(shift['culprit_current_share'], 0)}** in {current}."
                ),
            )
        )
    else:
        items.append(
            Evidence(
                kind="metric",
                direction="contradicts" if significant else "context",
                source="test_factor",
                text=f"The mix of leads by {label} is the same in {baseline} and {current}.",
            )
        )
    if significant and moved and test["explained_share"]:
        items.append(
            Evidence(
                kind="metric",
                direction="supports",
                source="test_factor",
                text=(
                    f"That shift alone accounts for about **{pct(test['explained_share'], 0)}** of the change "
                    f"({test['mix_effect_points']:+.1f} of {test['overall_change_points']:+.1f} points)."
                ),
            )
        )
    return items


def counterfactual_evidence(counterfactual: dict | None, test: dict) -> Evidence | None:
    if not counterfactual or abs(counterfactual["recoverable_points"]) < 0.3:
        return None
    return Evidence(
        kind="model",
        direction="supports" if counterfactual["recoverable_points"] > 0 else "contradicts",
        source="conversion model",
        text=(
            f"Model check: giving {month_name(test['current'])} leads the {test['label']} of "
            f"{month_name(test['baseline'])} moves predicted conversion by "
            f"**{counterfactual['recoverable_points']:+.1f} points**."
        ),
    )


def conversation_evidence(ds: Dataset, test: dict) -> list[Evidence]:
    items: list[Evidence] = []
    worst = test["gap"]["worst"]
    if worst:
        concentrated = analytics.themes_in_segment(ds, test["dimension"], worst)
        top = concentrated[0] if concentrated else None
        if top and is_concentrated(top):
            items.append(
                Evidence(
                    kind="conversation",
                    direction="supports",
                    source="conversation_themes",
                    text=(
                        f"Among lost “{worst}” leads, **{pct(top['rate_in_segment'], 0)}** raise "
                        f"{top['label']}, against **{pct(top['rate_elsewhere'], 0)}** of other lost leads."
                    ),
                )
            )
    claimed = CLAIMED_THEME.get(test["dimension"])
    themes = {t["theme"]: t for t in analytics.conversation_themes(ds)["themes"]}
    if claimed in themes and not items:
        theme = themes[claimed]
        lift = theme["lift"]
        telling = theme["p_value"] < 0.01 and (lift is None or lift >= 1.5)
        items.append(
            Evidence(
                kind="conversation",
                direction="supports" if telling else "contradicts",
                source="conversation_themes",
                text=(
                    f"**{pct(theme['mention_rate_lost'], 0)}** of lost customers bring up {theme['label']}"
                    + (
                        f", against **{pct(theme['mention_rate_won'], 0)}** of customers who bought."
                        if telling
                        else f", but so do **{pct(theme['mention_rate_won'], 0)}** of customers who bought."
                    )
                ),
            )
        )
    return items


def quote_evidence(quotes: list[dict], limit: int = 2) -> list[Evidence]:
    return [
        Evidence(
            kind="conversation",
            direction="context",
            source=f"lead {q.get('lead_id', '')}".strip(),
            text=f"“{q.get('quote') or q.get('text', '')}”",
        )
        for q in quotes[:limit]
        if q.get("quote") or q.get("text")
    ]


def policy_evidence(results: list[dict]) -> Evidence | None:
    if not results or results[0]["score"] < MIN_POLICY_SCORE:
        return None
    top = results[0]
    lines = [line.strip().lstrip("-•").strip() for line in top["text"].replace("**", "").splitlines()]
    excerpt = " ".join(line for line in lines if line)
    if len(excerpt) > 260:
        excerpt = excerpt[:257].rsplit(" ", 1)[0] + "…"
    return Evidence(kind="policy", direction="context", source=top["citation"], text=excerpt)


def impact_for(ds: Dataset, test: dict, counterfactual: dict | None, label: str) -> Impact | None:
    if label == "primary" and counterfactual and counterfactual["recoverable_points"] >= 0.3:
        return Impact(
            points=counterfactual["recoverable_points"],
            orders=counterfactual["recoverable_orders"],
            revenue=counterfactual["recoverable_revenue"],
            basis=f"model estimate if {test['label']} returned to its {month_name(test['baseline'])} level",
        )
    if label in {"primary", "chronic"}:
        rates = sorted(s["conversion_rate"] for s in test["segments"] if s["leads"] >= analytics.MIN_SEGMENT)
        worst = next(s for s in test["segments"] if s["segment"] == test["gap"]["worst"])
        if len(rates) < 2:
            return None
        typical = rates[len(rates) // 2]
        leads = worst["current_share"] * len(ds.leads_in(test["current"]))
        orders = leads * max(0.0, typical - worst["conversion_rate"])
        if orders < 0.5:
            return None
        return Impact(
            orders=round(orders, 1),
            revenue=round(orders * ds.average_order_value),
            basis=f"if “{worst['segment']}” converted like the typical segment, per month",
        )
    return None
