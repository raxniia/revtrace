from __future__ import annotations

import math

import numpy as np
from scipy import stats


def two_proportion_p(x1: int, n1: int, x2: int, n2: int) -> float:
    if min(n1, n2) == 0:
        return 1.0
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (x1 / n1 - x2 / n2) / se
    return float(2 * stats.norm.sf(abs(z)))


def chi2_p(table: np.ndarray) -> float:
    table = np.asarray(table, dtype=float)
    table = table[:, table.sum(axis=0) > 0]
    table = table[table.sum(axis=1) > 0]
    if table.shape[0] < 2 or table.shape[1] < 2:
        return 1.0
    return float(stats.chi2_contingency(table)[1])


def strength(p: float, scale: float = 6.0) -> float:
    return min(1.0, -math.log10(max(p, 1e-300)) / scale)


def wilson(x: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = x / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)
