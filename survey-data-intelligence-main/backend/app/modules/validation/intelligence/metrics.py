from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable

import numpy as np
import pandas as pd

from app.modules.sirl.profiler import json_safe


def series_missing_rate(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    total = int(frame.shape[0] * frame.shape[1])
    if total == 0:
        return 0.0
    return float(frame.isna().sum().sum() / total)


def employment_rate(series: pd.Series | None) -> float | None:
    if series is None:
        return None
    values = series.dropna().astype(str).str.lower()
    if values.empty:
        return None
    employed = values.str.contains("employ") & ~values.str.contains("unemploy")
    return float(employed.mean())


def unemployment_rate(series: pd.Series | None) -> float | None:
    if series is None:
        return None
    values = series.dropna().astype(str).str.lower()
    if values.empty:
        return None
    return float(values.str.contains("unemploy").mean())


def category_entropy(series: pd.Series | None) -> float | None:
    if series is None:
        return None
    values = series.dropna().astype(str)
    if values.empty:
        return None
    counts = values.value_counts(normalize=True)
    return float(-np.sum(counts * np.log2(counts.clip(lower=1e-12))))


def numeric_stats(series: pd.Series | None) -> dict[str, Any]:
    if series is None:
        return {}
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return {"n": 0}
    return {
        "n": int(len(numeric)),
        "mean": json_safe(float(numeric.mean())),
        "median": json_safe(float(numeric.median())),
        "std": json_safe(float(numeric.std(ddof=1))) if len(numeric) > 1 else 0.0,
        "zero_rate": json_safe(float((numeric == 0).mean())),
    }


def robust_z(value: float, median: float, mad: float) -> float | None:
    if mad is None or mad == 0 or math.isnan(mad):
        return None
    return 0.6745 * (value - median) / mad


def signature(row: dict[str, Any], fields: Iterable[str], income_band: bool = True) -> str:
    parts = []
    for field in fields:
        value = row.get(field)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            parts.append(f"{field}:")
            continue
        if income_band and field == "income":
            try:
                number = float(value)
                band = int(number // 5000) * 5000
                parts.append(f"income:{band}")
            except (TypeError, ValueError):
                parts.append(f"income:{value}")
            continue
        if field in {"working_hours", "hours"}:
            try:
                hours = int(round(float(value) / 5.0) * 5)
                parts.append(f"hours:{hours}")
            except (TypeError, ValueError):
                parts.append(f"{field}:{value}")
            continue
        if field == "age":
            try:
                age = int(float(value) // 5 * 5)
                parts.append(f"age:{age}")
            except (TypeError, ValueError):
                parts.append(f"age:{value}")
            continue
        parts.append(f"{field}:{str(value).strip().lower()}")
    return "|".join(parts)


def duplicate_counts(signatures: list[str]) -> Counter:
    return Counter(signatures)


def psi(expected: np.ndarray, actual: np.ndarray, bins: int = 8) -> float | None:
    expected = np.asarray(expected, dtype=float)
    actual = np.asarray(actual, dtype=float)
    expected = expected[np.isfinite(expected)]
    actual = actual[np.isfinite(actual)]
    if len(expected) < 8 or len(actual) < 8:
        return None
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return None
    e_counts, _ = np.histogram(expected, bins=edges)
    a_counts, _ = np.histogram(actual, bins=edges)
    e_prop = (e_counts + 1e-6) / (e_counts.sum() + 1e-6 * len(e_counts))
    a_prop = (a_counts + 1e-6) / (a_counts.sum() + 1e-6 * len(a_counts))
    return float(np.sum((a_prop - e_prop) * np.log(a_prop / e_prop)))


def categorical_tvd(expected: dict[str, int], actual: dict[str, int]) -> float:
    keys = set(expected) | set(actual)
    e_total = sum(expected.values()) or 1
    a_total = sum(actual.values()) or 1
    return 0.5 * sum(abs(actual.get(k, 0) / a_total - expected.get(k, 0) / e_total) for k in keys)
