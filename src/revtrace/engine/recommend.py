from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from .schema import Action, Hypothesis, Recommendation

if TYPE_CHECKING:
    from .investigation import Investigation

LEAD_TRAITS = {"qualified"}
DEFAULT_MESSAGE = (
    "Bonjour, je reviens vers vous au sujet de votre demande. Êtes-vous toujours intéressé(e) ? "
    "Nous pouvons vous proposer une facilité de paiement et une livraison rapide."
)

PLAYS: dict[str, dict] = {
    "response_time": {
        "title": "Alert the sales lead when a new lead waits more than {sla} minutes",
        "rationale": "Reply speed is the factor that changed most, and late replies convert far worse.",
        "effort": "low",
        "action": "alert_rule",
    },
    "followups": {
        "title": "Queue a second follow-up for qualified leads still on a single touch",
        "rationale": "Single-touch leads convert at less than half the rate of leads contacted twice.",
        "effort": "low",
        "action": "followup_tasks",
    },
    "sales_rep": {
        "title": "Pair {segment} with a senior rep and rebalance lead assignment",
        "rationale": "The change in who handles leads lines up with the drop.",
        "effort": "medium",
        "action": "manager_note",
    },
    "product": {
        "title": "Remove what blocks “{segment}” deals",
        "rationale": "This product attracts a large share of leads and converts far below the others.",
        "effort": "high",
        "action": "manager_note",
    },
    "source": {
        "title": "Review spend and targeting on “{segment}”",
        "rationale": "Leads from this source convert well below the rest.",
        "effort": "medium",
        "action": "manager_note",
    },
    "price_band": {
        "title": "Review quotes landing in the “{segment}” band",
        "rationale": "Conversion falls as quotes move into this band, and more quotes land there now.",
        "effort": "medium",
        "action": "manager_note",
    },
}
FALLBACK_PLAY = {
    "title": "Review “{segment}” ({label})",
    "rationale": "This segment converts below the rest.",
    "effort": "medium",
    "action": "manager_note",
}


def focus_segment(hypothesis: Hypothesis) -> str:
    factor = hypothesis.factor or {}
    if hypothesis.verdict.label == "primary":
        return factor.get("shift", {}).get("culprit") or ""
    return factor.get("gap", {}).get("worst") or ""


def stale_leads(run: Investigation, limit: int = 25) -> list[str]:
    leads = run.ds.leads_in(run.current)
    if "followups_count" not in leads.columns:
        return []
    cutoff = leads.created_at.max() - pd.Timedelta(days=14)
    pool = leads[
        (~leads.won) & (leads.followups_count < run.ctx.settings.min_followups) & (leads.created_at >= cutoff)
    ]
    if "qualified" in pool.columns:
        pool = pool[pool.qualified == "qualified"]
    return pool.sort_values("created_at", ascending=False).lead_id.head(limit).tolist()


def build_action(
    run: Investigation, kind: str, hypothesis: Hypothesis | None, title: str, message: str | None = None
) -> Action | None:
    sla = run.ctx.settings.sla_response_minutes
    if kind == "alert_rule":
        return Action(
            type="alert_rule",
            label="Turn on alert",
            payload={"metric": "first_response_minutes", "threshold_minutes": sla, "notify": "sales lead"},
        )
    if kind == "followup_tasks":
        lead_ids = stale_leads(run)
        if not lead_ids:
            return None
        return Action(
            type="followup_tasks",
            label=f"Create {len(lead_ids)} follow-up tasks",
            payload={"lead_ids": lead_ids, "message": message or DEFAULT_MESSAGE, "due_in_hours": 24},
        )
    if kind == "manager_note":
        body = hypothesis.reasoning if hypothesis else ""
        return Action(
            type="manager_note",
            label="Send to sales lead",
            payload={"subject": title, "note": body},
        )
    return None


def playbook_recommendations(
    run: Investigation, hypotheses: list[Hypothesis], limit: int = 5
) -> list[Recommendation]:
    recs: list[Recommendation] = []
    actionable = [
        h
        for h in hypotheses
        if h.verdict.label in {"primary", "chronic"} and h.dimension and h.dimension not in LEAD_TRAITS
    ]
    actionable.sort(
        key=lambda h: (h.verdict.label != "primary", -((h.impact.revenue if h.impact else 0) or 0))
    )
    for hypothesis in actionable[:limit]:
        play = PLAYS.get(hypothesis.dimension, FALLBACK_PLAY)
        title = play["title"].format(
            segment=focus_segment(hypothesis),
            label=(hypothesis.factor or {}).get("label", hypothesis.dimension),
            sla=run.ctx.settings.sla_response_minutes,
        )
        recs.append(
            Recommendation(
                id=f"R{len(recs) + 1}",
                title=title,
                rationale=play["rationale"],
                hypothesis_id=hypothesis.id,
                effort=play["effort"],
                impact=hypothesis.impact,
                action=build_action(run, play["action"], hypothesis, title),
            )
        )
    for hypothesis in hypotheses:
        if hypothesis.dimension == "price_band" and hypothesis.verdict.label == "rejected":
            recs.append(
                Recommendation(
                    id=f"R{len(recs) + 1}",
                    title="Hold prices where they are",
                    rationale=(
                        "Customers talk about price whether they buy or not, and conversion is flat across "
                        "price bands. A discount would cost margin without fixing the drop."
                    ),
                    hypothesis_id=hypothesis.id,
                    effort="low",
                )
            )
    return recs
