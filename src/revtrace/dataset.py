from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED_LEAD_COLUMNS = {"lead_id", "created_at", "status"}
WON_STATUSES = {"won", "converted", "closed_won", "closed won", "sale"}
RESERVED_COLUMNS = {"lead_id", "created_at", "status", "lost_reason", "month", "day", "won", "hour"}
RESPONSE_LABELS = ["under 30 min", "30 min to 2 h", "over 2 h"]
FOLLOWUP_LABELS = ["single touch", "2+ touches"]
LABELS = {
    "response_time": "first response time",
    "followups": "follow-up depth",
    "product": "product",
    "price_band": "price band",
    "sales_rep": "sales rep",
    "source": "lead source",
    "wilaya": "region",
    "qualified": "lead qualification",
    "channel": "channel",
}
SOURCE_COLUMNS = {"response_time": "first_response_minutes", "followups": "followups_count"}


class DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class Dimension:
    name: str
    label: str
    segments: tuple[str, ...]
    derived_from: str | None = None


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "dataset"


class Dataset:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.name = self.path.name
        leads_file = self.path / "leads.csv"
        if not leads_file.exists():
            raise DatasetError(f"{self.name}: leads.csv is missing")
        self.leads = self._prepare_leads(pd.read_csv(leads_file))
        self.orders = self._read_optional("orders.csv")
        self.customers = self._read_optional("customers.csv")
        self.conversations = self._read_conversations()
        if "channel" not in self.leads.columns and self.conversations:
            channels = {c["lead_id"]: c.get("channel") for c in self.conversations.values()}
            mapped = self.leads.lead_id.map(channels)
            if mapped.notna().any():
                self.leads["channel"] = mapped.fillna("unknown")

    def _read_optional(self, filename: str) -> pd.DataFrame:
        file = self.path / filename
        return pd.read_csv(file) if file.exists() else pd.DataFrame()

    def _read_conversations(self) -> dict[str, dict]:
        file = self.path / "conversations.json"
        if not file.exists():
            return {}
        records = json.loads(file.read_text(encoding="utf-8"))
        return {str(r["lead_id"]): r for r in records if "lead_id" in r}

    def _prepare_leads(self, df: pd.DataFrame) -> pd.DataFrame:
        missing = REQUIRED_LEAD_COLUMNS - set(df.columns)
        if missing:
            raise DatasetError(f"{self.name}: leads.csv is missing columns {sorted(missing)}")
        df = df.copy()
        df["lead_id"] = df.lead_id.astype(str)
        df["created_at"] = pd.to_datetime(df.created_at, errors="coerce")
        df = df.dropna(subset=["created_at"]).reset_index(drop=True)
        if df.empty:
            raise DatasetError(f"{self.name}: no rows with a valid created_at")
        df["won"] = df.status.astype(str).str.lower().str.strip().isin(WON_STATUSES)
        df["month"] = df.created_at.dt.strftime("%Y-%m")
        df["day"] = df.created_at.dt.normalize()
        df["hour"] = df.created_at.dt.hour
        for col in df.columns:
            if col not in RESERVED_COLUMNS and pd.api.types.is_bool_dtype(df[col]):
                name = col.replace("_", " ")
                df[col] = np.where(df[col], name, f"not {name}")
        if "first_response_minutes" in df.columns:
            minutes = pd.to_numeric(df.first_response_minutes, errors="coerce")
            df["first_response_minutes"] = minutes
            df["response_time"] = pd.cut(minutes, [-np.inf, 30, 120, np.inf], labels=RESPONSE_LABELS).astype(
                object
            )
        if "followups_count" in df.columns:
            count = pd.to_numeric(df.followups_count, errors="coerce").fillna(0)
            df["followups_count"] = count
            df["followups"] = np.where(count >= 2, FOLLOWUP_LABELS[1], FOLLOWUP_LABELS[0])
        return df

    @cached_property
    def months(self) -> list[str]:
        return sorted(self.leads.month.unique())

    @cached_property
    def dimensions(self) -> dict[str, Dimension]:
        found: dict[str, Dimension] = {}
        for col in self.leads.columns:
            if col in RESERVED_COLUMNS or col in SOURCE_COLUMNS.values():
                continue
            series = self.leads[col]
            if pd.api.types.is_numeric_dtype(series):
                continue
            values = series.dropna().astype(str)
            n = values.nunique()
            if not 2 <= n <= 20:
                continue
            if col == "response_time":
                segments = tuple(s for s in RESPONSE_LABELS if s in set(values))
            elif col == "followups":
                segments = tuple(s for s in FOLLOWUP_LABELS if s in set(values))
            else:
                segments = tuple(values.value_counts().index)
            found[col] = Dimension(
                col, LABELS.get(col, col.replace("_", " ")), segments, SOURCE_COLUMNS.get(col)
            )
        return found

    @cached_property
    def currency(self) -> str:
        for col in self.orders.columns:
            if col.startswith("amount_"):
                return col.split("_", 1)[1].upper()
        return ""

    @cached_property
    def revenue_by_lead(self) -> pd.Series:
        if self.orders.empty or "lead_id" not in self.orders.columns:
            return pd.Series(dtype=float)
        amount = next((c for c in self.orders.columns if c.startswith("amount")), None)
        if amount is None:
            return pd.Series(dtype=float)
        orders = self.orders.dropna(subset=["lead_id"])
        return orders.groupby(orders.lead_id.astype(str))[amount].sum()

    @cached_property
    def average_order_value(self) -> float:
        return float(self.revenue_by_lead.mean()) if len(self.revenue_by_lead) else 0.0

    def dimension(self, name: str) -> Dimension:
        if name not in self.dimensions:
            raise DatasetError(f"Unknown dimension '{name}'. Available: {', '.join(self.dimensions)}")
        return self.dimensions[name]

    def leads_in(self, month: str | None) -> pd.DataFrame:
        if month is None:
            return self.leads
        if month not in self.months:
            raise DatasetError(f"No data for {month}. Available months: {', '.join(self.months)}")
        return self.leads[self.leads.month == month]

    def default_periods(self) -> tuple[str, str]:
        if len(self.months) < 2:
            raise DatasetError(f"{self.name}: at least two months of leads are needed to compare periods")
        return self.months[-1], self.months[-2]

    def revenue(self, leads: pd.DataFrame) -> float:
        if not len(self.revenue_by_lead):
            return 0.0
        return float(self.revenue_by_lead.reindex(leads.lead_id).fillna(0).sum())

    def docs(self) -> list[Path]:
        folder = self.path / "docs"
        if not folder.exists():
            return []
        return sorted(p for p in folder.iterdir() if p.suffix.lower() in {".md", ".txt"})

    def describe(self) -> dict:
        return {
            "name": self.name,
            "leads": int(len(self.leads)),
            "orders": int(len(self.orders)),
            "conversations": len(self.conversations),
            "documents": [p.name for p in self.docs()],
            "months": self.months,
            "currency": self.currency,
            "dimensions": [
                {"name": d.name, "label": d.label, "segments": list(d.segments)}
                for d in self.dimensions.values()
            ],
        }


class DatasetRegistry:
    def __init__(self, *folders: Path):
        self.folders = [Path(f) for f in folders]
        self._cache: dict[str, Dataset] = {}

    def names(self) -> list[str]:
        names = []
        for folder in self.folders:
            if folder.exists():
                names += [p.name for p in sorted(folder.iterdir()) if (p / "leads.csv").exists()]
        return list(dict.fromkeys(names))

    def get(self, name: str) -> Dataset:
        if name not in self._cache:
            for folder in self.folders:
                if (folder / name / "leads.csv").exists():
                    self._cache[name] = Dataset(folder / name)
                    break
            else:
                raise DatasetError(f"Dataset '{name}' not found")
        return self._cache[name]

    def invalidate(self, name: str) -> None:
        self._cache.pop(name, None)
