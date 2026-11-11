from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from .dataset import SOURCE_COLUMNS, Dataset

NUMERIC = ["first_response_minutes", "followups_count", "hour"]
MIN_ROWS = 400


class ConversionModel:
    def __init__(self, ds: Dataset, seed: int = 0):
        self.ds = ds
        self.seed = seed
        derived = set(SOURCE_COLUMNS)
        self.categorical = [d for d in ds.dimensions if d not in derived]
        self.numeric = [c for c in NUMERIC if c in ds.leads.columns]
        self.features = self.numeric + self.categorical
        self.pipeline: Pipeline | None = None
        self.card: dict = {"trained": False}
        if len(ds.leads) >= MIN_ROWS and ds.leads.won.nunique() == 2 and self.features:
            self._fit()

    def _frame(self, leads: pd.DataFrame) -> pd.DataFrame:
        frame = leads[self.features].copy()
        for col in self.categorical:
            frame[col] = frame[col].astype(str)
        return frame

    def _build(self) -> Pipeline:
        encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
        columns = ColumnTransformer(
            [("num", "passthrough", self.numeric), ("cat", encoder, self.categorical)]
        )
        mask = [False] * len(self.numeric) + [True] * len(self.categorical)
        classifier = HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.06, max_iter=150, categorical_features=mask, random_state=self.seed
        )
        return Pipeline([("columns", columns), ("classifier", classifier)])

    def _fit(self) -> None:
        X, y = self._frame(self.ds.leads), self.ds.leads.won.astype(int)
        folds = StratifiedKFold(5, shuffle=True, random_state=self.seed)
        proba = cross_val_predict(self._build(), X, y, cv=folds, method="predict_proba")[:, 1]
        self.pipeline = self._build().fit(X, y)
        importance = permutation_importance(
            self.pipeline, X, y, scoring="roc_auc", n_repeats=5, random_state=self.seed
        )
        drivers = sorted(
            zip(self.features, importance.importances_mean, strict=True), key=lambda pair: -pair[1]
        )
        self.card = {
            "trained": True,
            "algorithm": "HistGradientBoostingClassifier",
            "rows": int(len(X)),
            "features": self.features,
            "cv_auc": round(float(roc_auc_score(y, proba)), 3),
            "cv_brier": round(float(brier_score_loss(y, proba)), 4),
            "base_rate": round(float(y.mean()), 4),
            "drivers": [
                {"feature": name, "importance": round(float(max(value, 0.0)), 4)} for name, value in drivers
            ],
        }

    def counterfactual(self, dimension: str, current: str, baseline: str, draws: int = 8) -> dict | None:
        if self.pipeline is None:
            return None
        column = SOURCE_COLUMNS.get(dimension, dimension)
        if column not in self.features:
            return None
        cur, base = self.ds.leads_in(current), self.ds.leads_in(baseline)
        X = self._frame(cur)
        actual = float(self.pipeline.predict_proba(X)[:, 1].mean())
        rng = np.random.default_rng(self.seed)
        pool = self._frame(base)[column].to_numpy()
        restored = []
        for _ in range(draws):
            swapped = X.copy()
            swapped[column] = rng.choice(pool, size=len(X))
            restored.append(float(self.pipeline.predict_proba(swapped)[:, 1].mean()))
        gain = float(np.mean(restored)) - actual
        return {
            "dimension": dimension,
            "predicted_rate": round(actual, 4),
            "restored_rate": round(actual + gain, 4),
            "recoverable_points": round(gain * 100, 2),
            "recoverable_orders": round(gain * len(cur), 1),
            "recoverable_revenue": round(gain * len(cur) * self.ds.average_order_value),
        }
