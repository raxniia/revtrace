from __future__ import annotations

import numpy as np
import pandas as pd

from .dataset import Dataset, DatasetError
from .stats import chi2_p, two_proportion_p

MIN_SEGMENT = 30
NUMERIC_METRICS = ("first_response_minutes", "followups_count", "price_quoted")

THEMES: dict[str, dict] = {
    "price": {
        "label": "price objections",
        "keywords": ["ghali", "cher", "remise", "arkhas", "expensive", "discount", "too much"],
    },
    "slow_response": {
        "label": "complaints about slow replies",
        "keywords": ["ma jawbtounich", "attendu longtemps", "enfin", "nsit", "still waiting", "no answer"],
    },
    "delivery_delay": {
        "label": "lead-time objections",
        "keywords": ["semaines bezzaf", "trop long", "nstanna", "too long", "can't wait"],
    },
    "competitor": {
        "label": "bought elsewhere",
        "keywords": ["ailleurs", "wahed akhor", "elsewhere", "another store"],
    },
}


def _rate(frame: pd.DataFrame) -> float | None:
    return float(frame.won.mean()) if len(frame) else None


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None or pd.isna(value) else round(float(value), digits)


def sales_metrics(ds: Dataset, month: str) -> dict:
    leads = ds.leads_in(month)
    won = int(leads.won.sum())
    out = {
        "month": month,
        "leads": int(len(leads)),
        "won": won,
        "conversion_rate": _round(_rate(leads)),
        "revenue": round(ds.revenue(leads)),
        "currency": ds.currency,
    }
    if "first_response_minutes" in leads.columns:
        out["median_response_minutes"] = _round(leads.first_response_minutes.median(), 1)
    if "followups_count" in leads.columns:
        out["share_with_second_followup"] = _round((leads.followups_count >= 2).mean())
    return out


def compare_periods(ds: Dataset, current: str, baseline: str) -> dict:
    cur, base = sales_metrics(ds, current), sales_metrics(ds, baseline)
    delta = cur["conversion_rate"] - base["conversion_rate"]
    return {
        "current": cur,
        "baseline": base,
        "conversion_change_points": _round(delta * 100, 2),
        "conversion_change_relative": _round(delta / base["conversion_rate"])
        if base["conversion_rate"]
        else None,
        "revenue_change_relative": _round(cur["revenue"] / base["revenue"] - 1) if base["revenue"] else None,
        "lead_volume_change_relative": _round(cur["leads"] / base["leads"] - 1),
        "p_value": _round(two_proportion_p(cur["won"], cur["leads"], base["won"], base["leads"]), 6),
    }


def factor_test(ds: Dataset, dimension: str, current: str, baseline: str) -> dict:
    dim = ds.dimension(dimension)
    col = dim.name
    everything = ds.leads.dropna(subset=[col])
    cur = ds.leads_in(current).dropna(subset=[col])
    base = ds.leads_in(baseline).dropna(subset=[col])
    if cur.empty or base.empty:
        raise DatasetError(f"Not enough data to test '{dimension}' between {baseline} and {current}")

    overall_cur, overall_base = _rate(cur), _rate(base)
    change = overall_cur - overall_base
    pivot_rate = (overall_cur + overall_base) / 2

    segments = []
    mix = 0.0
    for name in dim.segments:
        seg_all = everything[everything[col].astype(str) == name]
        seg_cur = cur[cur[col].astype(str) == name]
        seg_base = base[base[col].astype(str) == name]
        rate_all = _rate(seg_all)
        rate_cur = _rate(seg_cur)
        rate_base = _rate(seg_base)
        fill_cur = rate_cur if rate_cur is not None else rate_base if rate_base is not None else rate_all
        fill_base = rate_base if rate_base is not None else rate_cur if rate_cur is not None else rate_all
        share_cur = len(seg_cur) / len(cur)
        share_base = len(seg_base) / len(base)
        contribution = (share_cur - share_base) * ((fill_cur + fill_base) / 2 - pivot_rate)
        mix += contribution
        segments.append(
            {
                "segment": name,
                "leads": int(len(seg_all)),
                "conversion_rate": _round(rate_all),
                "baseline_share": _round(share_base),
                "current_share": _round(share_cur),
                "baseline_rate": _round(rate_base),
                "current_rate": _round(rate_cur),
                "contribution_points": _round(contribution * 100, 3),
            }
        )

    sized = [s for s in segments if s["leads"] >= MIN_SEGMENT]
    best = max(sized, key=lambda s: s["conversion_rate"], default=None)
    worst = min(sized, key=lambda s: s["conversion_rate"], default=None)
    gap_table = np.array(
        [
            [everything[everything[col].astype(str) == s["segment"]].won.sum() for s in sized],
            [(~everything[everything[col].astype(str) == s["segment"]].won).sum() for s in sized],
        ]
    )
    shift_table = np.array(
        [
            [(cur[col].astype(str) == s["segment"]).sum() for s in segments],
            [(base[col].astype(str) == s["segment"]).sum() for s in segments],
        ]
    )
    relative_gap = 0.0
    if best and best["conversion_rate"]:
        relative_gap = (best["conversion_rate"] - worst["conversion_rate"]) / best["conversion_rate"]
    explained = 0.0
    if change and mix and (change < 0) == (mix < 0):
        explained = min(1.0, mix / change)
    culprit = min(segments, key=lambda s: s["contribution_points"] * (1 if change < 0 else -1))

    return {
        "dimension": dim.name,
        "label": dim.label,
        "current": current,
        "baseline": baseline,
        "overall_change_points": _round(change * 100, 2),
        "segments": segments,
        "gap": {
            "best": best["segment"] if best else None,
            "best_rate": best["conversion_rate"] if best else None,
            "worst": worst["segment"] if worst else None,
            "worst_rate": worst["conversion_rate"] if worst else None,
            "relative_gap": _round(relative_gap),
            "p_value": chi2_p(gap_table) if len(sized) > 1 else 1.0,
        },
        "shift": {
            "p_value": chi2_p(shift_table),
            "total_variation": _round(
                0.5 * sum(abs(s["current_share"] - s["baseline_share"]) for s in segments)
            ),
            "culprit": culprit["segment"],
            "culprit_baseline_share": culprit["baseline_share"],
            "culprit_current_share": culprit["current_share"],
        },
        "mix_effect_points": _round(mix * 100, 2),
        "explained_share": _round(explained),
    }


def metric_by_segment(ds: Dataset, metric: str, by: str, month: str | None = None) -> dict:
    if metric not in NUMERIC_METRICS or metric not in ds.leads.columns:
        available = [m for m in NUMERIC_METRICS if m in ds.leads.columns]
        raise DatasetError(f"Unknown metric '{metric}'. Available: {', '.join(available)}")
    dim = ds.dimension(by)
    leads = ds.leads_in(month)
    rows = []
    for name, group in leads.groupby(leads[dim.name].astype(str)):
        rows.append(
            {
                "segment": name,
                "leads": int(len(group)),
                "median": _round(group[metric].median(), 1),
                "mean": _round(group[metric].mean(), 1),
                "conversion_rate": _round(_rate(group)),
            }
        )
    return {"metric": metric, "by": by, "month": month or "all", "segments": rows}


def daily_series(ds: Dataset) -> list[dict]:
    daily = ds.leads.groupby("day").agg(leads=("won", "size"), won=("won", "sum")).sort_index()
    rolling = daily.rolling(7, min_periods=3).sum()
    rate = (rolling.won / rolling.leads).round(4)
    return [
        {
            "date": day.strftime("%Y-%m-%d"),
            "leads": int(row.leads),
            "won": int(row.won),
            "rate_7d": None if pd.isna(rate[day]) else float(rate[day]),
        }
        for day, row in daily.iterrows()
    ]


def detect_changepoint(ds: Dataset, min_days: int = 14) -> dict | None:
    daily = ds.leads.groupby("day").agg(leads=("won", "size"), won=("won", "sum")).sort_index()
    if len(daily) < 2 * min_days:
        return None
    leads, won = daily.leads.cumsum().to_numpy(), daily.won.cumsum().to_numpy()
    best = None
    for i in range(min_days, len(daily) - min_days):
        before_n, before_x = leads[i - 1], won[i - 1]
        after_n, after_x = leads[-1] - before_n, won[-1] - before_x
        p = two_proportion_p(int(before_x), int(before_n), int(after_x), int(after_n))
        if best is None or p < best["p_value"]:
            best = {
                "date": daily.index[i].strftime("%Y-%m-%d"),
                "rate_before": _round(before_x / before_n),
                "rate_after": _round(after_x / after_n),
                "p_value": p,
            }
    return best if best and best["p_value"] < 0.01 else None


def _client_text(conversation: dict) -> str:
    return " ".join(m["text"] for m in conversation.get("messages", []) if m.get("from") == "client").lower()


def _theme_flags(ds: Dataset) -> pd.DataFrame:
    cached = getattr(ds, "_theme_flags", None)
    if cached is not None:
        return cached
    rows = []
    for lead_id, conversation in ds.conversations.items():
        text = _client_text(conversation)
        rows.append(
            {"lead_id": lead_id} | {t: any(k in text for k in spec["keywords"]) for t, spec in THEMES.items()}
        )
    flags = pd.DataFrame(rows, columns=["lead_id", *THEMES]).merge(
        ds.leads[["lead_id", "won", "month"]], on="lead_id"
    )
    ds._theme_flags = flags
    return flags


def conversation_themes(ds: Dataset, current: str | None = None, baseline: str | None = None) -> dict:
    flags = _theme_flags(ds)
    if flags.empty:
        return {"conversations": 0, "themes": []}
    lost, won = flags[~flags.won], flags[flags.won]
    themes = []
    for theme, spec in THEMES.items():
        lost_rate, won_rate = float(lost[theme].mean()), float(won[theme].mean())
        entry = {
            "theme": theme,
            "label": spec["label"],
            "mention_rate_lost": _round(lost_rate),
            "mention_rate_won": _round(won_rate),
            "lift": _round(lost_rate / won_rate, 2) if won_rate else None,
            "p_value": two_proportion_p(int(lost[theme].sum()), len(lost), int(won[theme].sum()), len(won)),
            "conversations": int(flags[theme].sum()),
        }
        if current and baseline:
            entry["mention_rate_current"] = _round(flags[flags.month == current][theme].mean())
            entry["mention_rate_baseline"] = _round(flags[flags.month == baseline][theme].mean())
        themes.append(entry)
    return {"conversations": int(len(flags)), "themes": themes}


def themes_in_segment(ds: Dataset, dimension: str, segment: str) -> list[dict]:
    flags = _theme_flags(ds)
    if flags.empty:
        return []
    col = ds.dimension(dimension).name
    lost = flags[~flags.won].merge(ds.leads[["lead_id", col]], on="lead_id")
    inside = lost[lost[col].astype(str) == segment]
    outside = lost[lost[col].astype(str) != segment]
    if len(inside) < MIN_SEGMENT or outside.empty:
        return []
    out = []
    for theme, spec in THEMES.items():
        rate_in, rate_out = float(inside[theme].mean()), float(outside[theme].mean())
        out.append(
            {
                "theme": theme,
                "label": spec["label"],
                "rate_in_segment": _round(rate_in),
                "rate_elsewhere": _round(rate_out),
                "p_value": two_proportion_p(
                    int(inside[theme].sum()), len(inside), int(outside[theme].sum()), len(outside)
                ),
            }
        )
    return sorted(out, key=lambda t: t["rate_elsewhere"] - t["rate_in_segment"])


def search_conversations(
    ds: Dataset, query: str, status: str | None = None, month: str | None = None, limit: int = 5
) -> dict:
    terms = [t.strip() for t in query.lower().split(",") if t.strip()]
    if not terms:
        raise DatasetError("Provide at least one keyword")
    meta = ds.leads.set_index("lead_id")[["status", "month"]]
    matches = []
    for lead_id, conversation in ds.conversations.items():
        if lead_id not in meta.index:
            continue
        row = meta.loc[lead_id]
        if (status and row.status != status) or (month and row.month != month):
            continue
        hit = next(
            (
                m
                for m in conversation["messages"]
                if m.get("from") == "client" and any(t in m["text"].lower() for t in terms)
            ),
            None,
        )
        if hit:
            matches.append(
                {"lead_id": lead_id, "status": row.status, "month": row.month, "quote": hit["text"]}
            )
    return {"query": query, "matches": len(matches), "examples": matches[: max(1, min(limit, 20))]}


def get_conversation(ds: Dataset, lead_id: str) -> dict:
    if lead_id not in ds.conversations:
        raise DatasetError(f"No conversation for lead {lead_id}")
    return ds.conversations[lead_id]


def health(ds: Dataset, current: str, baseline: str, sla_minutes: int, min_followups: int) -> dict:
    cur = ds.leads_in(current)
    comparison = compare_periods(ds, current, baseline)
    relative = comparison["conversion_change_relative"] or 0.0
    components = [
        {
            "key": "momentum",
            "label": "Conversion against last period",
            "score": round(max(0.0, min(100.0, 100 + relative * 200))),
            "weight": 0.4,
            "detail": f"{relative:+.0%} versus {baseline}",
        }
    ]
    if "first_response_minutes" in cur.columns:
        within = float((cur.first_response_minutes <= sla_minutes).mean())
        components.append(
            {
                "key": "response",
                "label": f"Leads answered within {sla_minutes} minutes",
                "score": round(within * 100),
                "weight": 0.2,
                "detail": f"{within:.0%} of leads",
            }
        )
    if "followups_count" in cur.columns:
        pool = cur[cur.qualified == "qualified"] if "qualified" in cur.columns else cur
        done = float((pool.followups_count >= min_followups).mean()) if len(pool) else 0.0
        components.append(
            {
                "key": "followups",
                "label": "Qualified leads followed up twice",
                "score": round(done * 100),
                "weight": 0.2,
                "detail": f"{done:.0%} of qualified leads",
            }
        )
    if "product" in ds.dimensions:
        rates = cur.groupby("product").won.mean()
        if len(rates) > 1 and rates.median() > 0:
            balance = float(min(1.0, rates.min() / rates.median()))
            components.append(
                {
                    "key": "balance",
                    "label": "Weakest product against the typical one",
                    "score": round(balance * 100),
                    "weight": 0.2,
                    "detail": f"{rates.idxmin()} converts at {rates.min():.1%}",
                }
            )
    total_weight = sum(c["weight"] for c in components)
    score = round(sum(c["score"] * c["weight"] for c in components) / total_weight)
    return {"score": score, "components": components}
