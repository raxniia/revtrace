from __future__ import annotations

from .. import analytics
from .evidence import CLAIMED_THEME, is_concentrated, month_name, pct
from .investigation import Draft, Investigation, Notes
from .recommend import playbook_recommendations
from .schema import Evidence, Hypothesis, Recommendation

PRIORITY = ["response_time", "followups", "sales_rep", "product", "price_band", "source", "qualified"]
TEMPLATES: dict[str, tuple[str, str, str]] = {
    "response_time": (
        "Slow first response",
        "Leads wait longer for a first reply, and late replies convert worse.",
        "first response time délai première réponse minutes",
    ),
    "followups": (
        "Missing follow-ups",
        "Fewer leads get a second follow-up, and single-touch leads rarely convert.",
        "follow-up relance leads qualifiés 48 heures",
    ),
    "sales_rep": (
        "Change in the sales team",
        "Who handles the leads changed, and not every rep converts alike.",
        "répartition des leads commerciaux nouveau commercial assignment onboarding",
    ),
    "product": (
        "Product-specific friction",
        "One product attracts leads but loses them before the sale.",
        "délai livraison fabrication produit delivery lead time",
    ),
    "price_band": (
        "Prices are too high",
        "Higher quotes push customers away.",
        "politique de prix négociation remise positionnement pricing",
    ),
    "source": (
        "Lead source quality",
        "More leads come from sources that convert poorly.",
        "sources de leads acquisition campagne",
    ),
    "qualified": (
        "Lead quality",
        "A larger share of leads is unqualified.",
        "qualification des leads",
    ),
}


class BaselineStrategy:
    label = "baseline"

    def propose(self, run: Investigation) -> list[Draft]:
        if run.ds.conversations:
            run.tool("Conversation Agent", "conversation_themes", current=run.current, baseline=run.baseline)
        names = [d for d in PRIORITY if d in run.ds.dimensions]
        names += [d for d in run.ds.dimensions if d not in names]
        drafts = []
        for name in names:
            label = run.ds.dimensions[name].label
            title, statement, query = TEMPLATES.get(
                name, (f"Shift in {label}", f"The mix of leads by {label} changed.", label)
            )
            drafts.append(Draft(title, statement, name, query))
        return drafts

    def investigate(self, run: Investigation, draft: Draft) -> Notes:
        notes = Notes(dimension=draft.dimension)
        test = run.test(draft.dimension)
        if not test:
            return notes
        theme = self._theme(run, test)
        if theme:
            keywords = ", ".join(analytics.THEMES[theme]["keywords"][:3])
            found = run.tool(
                "Conversation Agent",
                "search_conversations",
                query=keywords,
                status="lost",
                month=run.current,
                limit=2,
            )
            notes.quotes = found.get("examples", [])
        source = run.ds.dimensions[draft.dimension].derived_from
        if source and "sales_rep" in run.ds.dimensions and test["shift"]["p_value"] < 0.01:
            spread = run.tool(
                "Data Analyst", "metric_by_segment", metric=source, by="sales_rep", month=run.current
            )
            rows = [
                r for r in spread.get("segments", []) if r["leads"] >= analytics.MIN_SEGMENT and r["median"]
            ]
            if len(rows) > 1:
                high, low = max(rows, key=lambda r: r["median"]), min(rows, key=lambda r: r["median"])
                if high["median"] >= 2 * low["median"]:
                    notes.extra.append(
                        Evidence(
                            kind="metric",
                            direction="context",
                            source="metric_by_segment",
                            text=(
                                f"In {month_name(run.current)}, {high['segment']}'s median "
                                f"{source.replace('_', ' ')} is **{high['median']:.0f}** against "
                                f"**{low['median']:.0f}** for {low['segment']}."
                            ),
                        )
                    )
        return notes

    def _theme(self, run: Investigation, test: dict) -> str | None:
        worst = test["gap"]["worst"]
        concentrated = analytics.themes_in_segment(run.ds, test["dimension"], worst) if worst else []
        if concentrated and is_concentrated(concentrated[0]):
            return concentrated[0]["theme"]
        return CLAIMED_THEME.get(test["dimension"])

    def explain(self, run: Investigation, hypothesis: Hypothesis, notes: Notes) -> str:
        factor = hypothesis.factor
        if not factor:
            return "There was not enough data to test this."
        gap, shift = factor["gap"], factor["shift"]
        current, baseline = month_name(run.current), month_name(run.baseline)
        if hypothesis.verdict.label == "primary":
            return (
                f"Supported. By {factor['label']}, “{gap['worst']}” converts at {pct(gap['worst_rate'])} against "
                f"{pct(gap['best_rate'])} for “{gap['best']}”, and the share of leads in “{shift['culprit']}” moved "
                f"from {pct(shift['culprit_baseline_share'], 0)} to {pct(shift['culprit_current_share'], 0)} between "
                f"{baseline} and {current}. That shift accounts for about {pct(factor['explained_share'], 0)} "
                f"of the change in conversion."
            )
        if hypothesis.verdict.label == "chronic":
            return (
                f"A real leak, but not what changed. “{gap['worst']}” converts at {pct(gap['worst_rate'])} against "
                f"{pct(gap['best_rate'])} for “{gap['best']}”, yet the mix by {factor['label']} is the same in "
                f"{baseline} and {current}. It was costing sales before the drop and still is."
            )
        if gap["p_value"] < 0.01:
            return (
                f"Ruled out as a cause. “{gap['worst']}” leads do convert less ({pct(gap['worst_rate'])} against "
                f"{pct(gap['best_rate'])}), but their share is the same in {baseline} and {current}."
            )
        return (
            f"Ruled out. Conversion is statistically flat across {factor['label']} "
            f"(p = {gap['p_value']:.2f}), so this cannot explain the change."
        )

    def conclude(self, run: Investigation, hypotheses: list[Hypothesis]) -> tuple[str, list[Recommendation]]:
        return self.summary(run, hypotheses), playbook_recommendations(run, hypotheses)

    @staticmethod
    def summary(run: Investigation, hypotheses: list[Hypothesis]) -> str:
        comparison = run.situation["comparison"]
        current, baseline = month_name(run.current), month_name(run.baseline)
        direction = "fell" if comparison["conversion_change_points"] < 0 else "rose"
        parts = [
            f"Conversion {direction} from {pct(comparison['baseline']['conversion_rate'])} in {baseline} to "
            f"{pct(comparison['current']['conversion_rate'])} in {current}."
        ]
        if comparison["p_value"] >= 0.05:
            parts.append("The change is within normal month-to-month variation.")
        primary = [h.title.lower() for h in hypotheses if h.verdict.label == "primary"]
        chronic = [h.title.lower() for h in hypotheses if h.verdict.label == "chronic"]
        rejected = [h.title.lower() for h in hypotheses if h.verdict.label == "rejected"]
        if primary:
            parts.append(f"The evidence points to {_join(primary)}.")
        else:
            parts.append("None of the tested factors explains the change.")
        if chronic:
            parts.append(
                f"Separately, {_join(chronic)} {'is' if len(chronic) == 1 else 'are'} a standing leak."
            )
        if rejected:
            parts.append(f"Ruled out: {_join(rejected)}.")
        return " ".join(parts)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
