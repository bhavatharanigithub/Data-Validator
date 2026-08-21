from __future__ import annotations

import numpy as np
import pandas as pd

from app.models import DetectorConfig
from app.modules.sirl.profiler import ColumnRoles, json_safe
from app.modules.validation.intelligence.metrics import unemployment_rate
from app.modules.validation.intelligence.registry import is_enabled, thresholds
from app.modules.validation.intelligence.types import (
    EMPLOYMENT_CANDIDATES,
    PERIOD_CANDIDATES,
    UNUSUAL_PATTERN,
    Detection,
    DetectorOutcome,
    first_column,
)


def evaluate_temporal(
    frame: pd.DataFrame,
    roles: ColumnRoles,
    configs: dict[str, DetectorConfig],
) -> DetectorOutcome:
    if not is_enabled(configs, "TEMPORAL_CHANGE"):
        return DetectorOutcome(available=False, skipped=True, reason="TEMPORAL_CHANGE disabled")
    period_col = first_column(list(frame.columns), PERIOD_CANDIDATES)
    emp_col = first_column(list(frame.columns), EMPLOYMENT_CANDIDATES)
    if not period_col:
        return DetectorOutcome(
            available=False, skipped=True, reason="No previous survey period available"
        )
    if not emp_col:
        return DetectorOutcome(available=False, skipped=True, reason="No employment field for temporal rates")
    periods = [str(v) for v in frame[period_col].dropna().astype(str).unique()]
    if len(periods) < 2:
        return DetectorOutcome(
            available=False, skipped=True, reason="INSUFFICIENT HISTORICAL DATA — fewer than two periods"
        )
    cfg = thresholds(configs, "TEMPORAL_CHANGE")
    min_n = int(cfg.get("min_period_n", 8))
    pp = float(cfg.get("pp_threshold", 0.08))
    ordered = sorted(periods)
    stats = []
    for period in ordered:
        subset = frame.loc[frame[period_col].astype(str) == period]
        rate = unemployment_rate(subset[emp_col])
        stats.append({"period": period, "n": int(len(subset)), "unemployment_rate": rate})
    detections: list[Detection] = []
    rates = [item["unemployment_rate"] for item in stats if item["unemployment_rate"] is not None]
    rolling_mean = float(np.mean(rates)) if rates else None
    rolling_std = float(np.std(rates, ddof=1)) if len(rates) > 1 else None
    ewma = None
    cusum = 0.0
    for index, item in enumerate(stats):
        if item["n"] < min_n or item["unemployment_rate"] is None:
            continue
        previous = stats[index - 1] if index else None
        if previous and previous["unemployment_rate"] is not None and previous["n"] >= min_n:
            change = item["unemployment_rate"] - previous["unemployment_rate"]
            if abs(change) >= pp:
                detections.append(
                    Detection(
                        entity_type="state",
                        entity_id=str(item["period"]),
                        detector_type="TEMPORAL_CHANGE",
                        category="TEMPORAL",
                        classification=UNUSUAL_PATTERN,
                        severity="HIGH" if abs(change) >= 0.12 else "MEDIUM",
                        explanation="Period-over-period unemployment rate changed substantially versus the previous comparable period.",
                        field_name="unemployment_rate",
                        observed_value=json_safe(item["unemployment_rate"]),
                        expected_value=json_safe(previous["unemployment_rate"]),
                        deviation=json_safe(change),
                        baseline_type="previous_period",
                        evidence={
                            "current_period": item["period"],
                            "previous_period": previous["period"],
                            "percentage_point_change": json_safe(change),
                            "rolling_mean": json_safe(rolling_mean),
                            "rolling_std": json_safe(rolling_std),
                        },
                    )
                )
        if rolling_mean is not None and rolling_std and rolling_std > 1e-9:
            z = (item["unemployment_rate"] - rolling_mean) / rolling_std
            if abs(z) >= 2.5:
                detections.append(
                    Detection(
                        entity_type="state",
                        entity_id=str(item["period"]),
                        detector_type="TEMPORAL_CHANGE",
                        category="TEMPORAL",
                        classification=UNUSUAL_PATTERN,
                        severity="MEDIUM",
                        explanation="Unemployment rate deviates from the rolling historical baseline for this survey.",
                        field_name="unemployment_rate",
                        observed_value=json_safe(item["unemployment_rate"]),
                        expected_value=json_safe(rolling_mean),
                        deviation=json_safe(item["unemployment_rate"] - rolling_mean),
                        baseline_type="rolling_mean",
                        evidence={"robust_z_score": json_safe(z)},
                    )
                )
        ewma = item["unemployment_rate"] if ewma is None else 0.4 * item["unemployment_rate"] + 0.6 * ewma
        if ewma is not None:
            cusum = max(0.0, cusum + item["unemployment_rate"] - ewma)
            if cusum >= 0.15:
                detections.append(
                    Detection(
                        entity_type="state",
                        entity_id=str(item["period"]),
                        detector_type="TEMPORAL_CHANGE",
                        category="TEMPORAL",
                        classification=UNUSUAL_PATTERN,
                        severity="MEDIUM",
                        explanation="CUSUM/EWMA change-point signal on unemployment rate — investigation candidate, not proof of error.",
                        field_name="unemployment_rate",
                        observed_value=json_safe(item["unemployment_rate"]),
                        expected_value=json_safe(ewma),
                        deviation=json_safe(cusum),
                        baseline_type="ewma_cusum",
                        evidence={"cusum": json_safe(cusum), "ewma": json_safe(ewma)},
                    )
                )
                cusum = 0.0
    return DetectorOutcome(available=True, detections=detections)
