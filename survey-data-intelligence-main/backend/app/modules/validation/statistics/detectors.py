"""Deterministic statistical detectors.

Severity values are evidence labels only. They are not risk weights.

Z-score / group z-score:
  |z| < z_medium                 not persisted
  z_medium <= |z| < z_high       MEDIUM
  |z| >= z_high                  HIGH

IQR (Tukey):
  outside inner fence (multiplier, default 1.5)   MEDIUM
  outside outer fence (outer multiplier, default 3.0) HIGH

Historical shift (dataset grain):
  if historical std is usable, apply the z-score mapping to
      (current_mean - historical_mean) / historical_std
  otherwise use relative change |delta| / max(|historical_mean|, epsilon):
      relative_medium <= r < relative_high   MEDIUM
      r >= relative_high                     HIGH
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.modules.sirl.profiler import json_safe
from app.modules.validation.statistics.baselines import StatsThresholds, usable_std


def z_severity(abs_z: float, thresholds: StatsThresholds) -> str | None:
    if abs_z < thresholds.z_medium:
        return None
    if abs_z < thresholds.z_high:
        return "MEDIUM"
    return "HIGH"


def iqr_severity(
    value: float,
    lower_inner: float,
    upper_inner: float,
    lower_outer: float,
    upper_outer: float,
) -> str | None:
    if value < lower_outer or value > upper_outer:
        return "HIGH"
    if value < lower_inner or value > upper_inner:
        return "MEDIUM"
    return None


def _evidence(
    *,
    variable: str,
    detector: str,
    scope: str,
    severity: str,
    observed_value: float | None,
    baseline_value: float | None,
    baseline_std: float | None,
    score: float | None,
    threshold: float | None,
    record_id: str | None = None,
    enumerator_id: str | None = None,
    cluster_id: str | None = None,
    district_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "record_id": record_id,
        "variable": variable,
        "detector": detector,
        "scope": scope,
        "observed_value": json_safe(observed_value),
        "baseline_mean": json_safe(baseline_value),
        "baseline_std": json_safe(baseline_std),
        "score": json_safe(score),
        "threshold": json_safe(threshold),
        "severity": severity,
        "enumerator_id": enumerator_id,
        "cluster_id": cluster_id,
        "district_id": district_id,
    }
    if extra:
        payload.update(extra)
    return {
        "record_id": record_id,
        "enumerator_id": enumerator_id,
        "cluster_id": cluster_id,
        "district_id": district_id,
        "variable": variable,
        "detector": detector,
        "scope": scope,
        "observed_value": json_safe(observed_value),
        "baseline_value": json_safe(baseline_value),
        "baseline_std": json_safe(baseline_std),
        "score": json_safe(score),
        "threshold": json_safe(threshold),
        "severity": severity,
        "evidence_json": payload,
    }


def detect_z_score(
    numeric: pd.Series,
    *,
    variable: str,
    thresholds: StatsThresholds,
    record_ids: pd.Series,
    enumerator_ids: pd.Series,
    cluster_ids: pd.Series,
    district_ids: pd.Series,
) -> list[dict[str, Any]]:
    valid = numeric.dropna()
    n = int(valid.shape[0])
    if n < thresholds.min_observations:
        return []
    mean = float(valid.mean())
    std = float(valid.std(ddof=1)) if n > 1 else 0.0
    if not usable_std(std, thresholds.std_epsilon):
        return []
    z = (numeric - mean) / std
    abs_z = z.abs()
    mask = numeric.notna() & (abs_z >= thresholds.z_medium)
    if not bool(mask.any()):
        return []
    detections: list[dict[str, Any]] = []
    flagged = abs_z.index[mask]
    z_values = z.loc[flagged].to_numpy()
    observed = numeric.loc[flagged].to_numpy()
    rec = record_ids.loc[flagged].to_numpy()
    enum = enumerator_ids.loc[flagged].to_numpy()
    clus = cluster_ids.loc[flagged].to_numpy()
    dist = district_ids.loc[flagged].to_numpy()
    for i in range(len(flagged)):
        score = float(z_values[i])
        severity = z_severity(abs(score), thresholds)
        if severity is None:
            continue
        detections.append(
            _evidence(
                variable=variable,
                detector="z_score",
                scope="dataset",
                severity=severity,
                observed_value=float(observed[i]),
                baseline_value=mean,
                baseline_std=std,
                score=score,
                threshold=thresholds.z_high if abs(score) >= thresholds.z_high else thresholds.z_medium,
                record_id=None if rec[i] is None else str(rec[i]),
                enumerator_id=None if enum[i] is None else str(enum[i]),
                cluster_id=None if clus[i] is None else str(clus[i]),
                district_id=None if dist[i] is None else str(dist[i]),
            )
        )
    return detections


def detect_mad(
    numeric: pd.Series,
    *,
    variable: str,
    thresholds: StatsThresholds,
    record_ids: pd.Series,
    enumerator_ids: pd.Series,
    cluster_ids: pd.Series,
    district_ids: pd.Series,
) -> list[dict[str, Any]]:
    valid = numeric.dropna()
    n = int(valid.shape[0])
    if n < thresholds.min_observations:
        return []
    median = float(valid.median())
    mad = float((valid - median).abs().median())
    if not usable_std(mad, thresholds.std_epsilon):
        return []
    robust = 0.6745 * (numeric - median) / mad
    abs_z = robust.abs()
    mask = numeric.notna() & (abs_z >= thresholds.z_medium)
    if not bool(mask.any()):
        return []
    detections: list[dict[str, Any]] = []
    flagged = abs_z.index[mask]
    scores = robust.loc[flagged].to_numpy()
    observed = numeric.loc[flagged].to_numpy()
    rec = record_ids.loc[flagged].to_numpy()
    enum = enumerator_ids.loc[flagged].to_numpy()
    clus = cluster_ids.loc[flagged].to_numpy()
    dist = district_ids.loc[flagged].to_numpy()
    for i in range(len(flagged)):
        score = float(scores[i])
        severity = z_severity(abs(score), thresholds)
        if severity is None:
            continue
        detections.append(
            _evidence(
                variable=variable,
                detector="mad",
                scope="dataset",
                severity=severity,
                observed_value=float(observed[i]),
                baseline_value=median,
                baseline_std=mad,
                score=score,
                threshold=thresholds.z_high if abs(score) >= thresholds.z_high else thresholds.z_medium,
                record_id=None if rec[i] is None else str(rec[i]),
                enumerator_id=None if enum[i] is None else str(enum[i]),
                cluster_id=None if clus[i] is None else str(clus[i]),
                district_id=None if dist[i] is None else str(dist[i]),
                extra={"method": "robust_z_score"},
            )
        )
    return detections


def detect_iqr(
    numeric: pd.Series,
    *,
    variable: str,
    thresholds: StatsThresholds,
    record_ids: pd.Series,
    enumerator_ids: pd.Series,
    cluster_ids: pd.Series,
    district_ids: pd.Series,
) -> list[dict[str, Any]]:
    valid = numeric.dropna()
    n = int(valid.shape[0])
    if n < thresholds.min_observations:
        return []
    q1 = float(valid.quantile(0.25))
    q3 = float(valid.quantile(0.75))
    iqr = q3 - q1
    if not usable_std(iqr, thresholds.std_epsilon):
        return []
    inner = thresholds.iqr_multiplier
    outer = thresholds.iqr_outer_multiplier
    lower_inner = q1 - inner * iqr
    upper_inner = q3 + inner * iqr
    lower_outer = q1 - outer * iqr
    upper_outer = q3 + outer * iqr
    mask = numeric.notna() & ((numeric < lower_inner) | (numeric > upper_inner))
    if not bool(mask.any()):
        return []
    detections: list[dict[str, Any]] = []
    flagged = numeric.index[mask]
    observed = numeric.loc[flagged].to_numpy()
    rec = record_ids.loc[flagged].to_numpy()
    enum = enumerator_ids.loc[flagged].to_numpy()
    clus = cluster_ids.loc[flagged].to_numpy()
    dist = district_ids.loc[flagged].to_numpy()
    for i in range(len(flagged)):
        value = float(observed[i])
        severity = iqr_severity(value, lower_inner, upper_inner, lower_outer, upper_outer)
        if severity is None:
            continue
        fence = outer if severity == "HIGH" else inner
        detections.append(
            _evidence(
                variable=variable,
                detector="iqr",
                scope="dataset",
                severity=severity,
                observed_value=value,
                baseline_value=float(valid.median()),
                baseline_std=iqr,
                score=value,
                threshold=fence,
                record_id=None if rec[i] is None else str(rec[i]),
                enumerator_id=None if enum[i] is None else str(enum[i]),
                cluster_id=None if clus[i] is None else str(clus[i]),
                district_id=None if dist[i] is None else str(dist[i]),
                extra={
                    "q1": json_safe(q1),
                    "q3": json_safe(q3),
                    "iqr": json_safe(iqr),
                    "lower": json_safe(lower_inner if severity == "MEDIUM" else lower_outer),
                    "upper": json_safe(upper_inner if severity == "MEDIUM" else upper_outer),
                    "baseline_mean": json_safe(float(valid.mean())),
                },
            )
        )
    return detections


def detect_group_z_score(
    frame: pd.DataFrame,
    numeric: pd.Series,
    *,
    variable: str,
    group_col: str,
    scope: str,
    thresholds: StatsThresholds,
    record_ids: pd.Series,
    enumerator_ids: pd.Series,
    cluster_ids: pd.Series,
    district_ids: pd.Series,
) -> list[dict[str, Any]]:
    if group_col not in frame.columns:
        return []
    grouped = numeric.groupby(frame[group_col], dropna=True)
    counts = grouped.transform("count")
    means = grouped.transform("mean")
    stds = grouped.transform("std")
    eligible = (
        numeric.notna()
        & frame[group_col].notna()
        & (counts >= thresholds.min_group_observations)
        & (stds.abs() >= thresholds.std_epsilon)
        & stds.notna()
    )
    if not bool(eligible.any()):
        return []
    z = pd.Series(np.nan, index=numeric.index)
    z.loc[eligible] = (numeric.loc[eligible] - means.loc[eligible]) / stds.loc[eligible]
    abs_z = z.abs()
    mask = eligible & (abs_z >= thresholds.z_medium)
    if not bool(mask.any()):
        return []
    detections: list[dict[str, Any]] = []
    flagged = numeric.index[mask]
    z_values = z.loc[flagged].to_numpy()
    observed = numeric.loc[flagged].to_numpy()
    group_ids = frame.loc[flagged, group_col].map(lambda value: str(value)).to_numpy()
    group_means = means.loc[flagged].to_numpy()
    group_stds = stds.loc[flagged].to_numpy()
    rec = record_ids.loc[flagged].to_numpy()
    enum = enumerator_ids.loc[flagged].to_numpy()
    clus = cluster_ids.loc[flagged].to_numpy()
    dist = district_ids.loc[flagged].to_numpy()
    for i in range(len(flagged)):
        score = float(z_values[i])
        severity = z_severity(abs(score), thresholds)
        if severity is None:
            continue
        detections.append(
            _evidence(
                variable=variable,
                detector="group_z_score",
                scope=scope,
                severity=severity,
                observed_value=float(observed[i]),
                baseline_value=float(group_means[i]),
                baseline_std=float(group_stds[i]),
                score=score,
                threshold=thresholds.z_high if abs(score) >= thresholds.z_high else thresholds.z_medium,
                record_id=None if rec[i] is None else str(rec[i]),
                enumerator_id=None if enum[i] is None else str(enum[i]),
                cluster_id=None if clus[i] is None else str(clus[i]),
                district_id=None if dist[i] is None else str(dist[i]),
                extra={"group_id": str(group_ids[i])},
            )
        )
    return detections


def detect_historical_shift(
    current_means: dict[str, float],
    historical: dict[str, dict[str, float | str | None]],
    thresholds: StatsThresholds,
) -> list[dict[str, Any]]:
    """Dataset-level comparison against a prior batch. Never uses the current batch as history."""
    detections: list[dict[str, Any]] = []
    for variable, observed_mean in current_means.items():
        prior = historical.get(variable)
        if not prior or prior.get("mean") is None:
            continue
        hist_mean = float(prior["mean"])
        hist_std = prior.get("std")
        std_value = None if hist_std is None else float(hist_std)
        extra = {"source_batch_id": prior.get("source_batch_id"), "comparison": "current_vs_historical"}
        if usable_std(std_value, thresholds.std_epsilon):
            score = (observed_mean - hist_mean) / float(std_value)
            severity = z_severity(abs(score), thresholds)
            if severity is None:
                continue
            detections.append(
                _evidence(
                    variable=variable,
                    detector="historical_shift",
                    scope="dataset",
                    severity=severity,
                    observed_value=observed_mean,
                    baseline_value=hist_mean,
                    baseline_std=float(std_value),
                    score=float(score),
                    threshold=thresholds.z_high if abs(score) >= thresholds.z_high else thresholds.z_medium,
                    extra=extra,
                )
            )
            continue
        denom = max(abs(hist_mean), thresholds.std_epsilon)
        relative = abs(observed_mean - hist_mean) / denom
        if relative < thresholds.historical_relative_medium:
            continue
        severity = (
            "HIGH" if relative >= thresholds.historical_relative_high else "MEDIUM"
        )
        detections.append(
            _evidence(
                variable=variable,
                detector="historical_shift",
                scope="dataset",
                severity=severity,
                observed_value=observed_mean,
                baseline_value=hist_mean,
                baseline_std=std_value,
                score=float(relative),
                threshold=(
                    thresholds.historical_relative_high
                    if severity == "HIGH"
                    else thresholds.historical_relative_medium
                ),
                extra={**extra, "metric": "relative_change"},
            )
        )
    return detections
