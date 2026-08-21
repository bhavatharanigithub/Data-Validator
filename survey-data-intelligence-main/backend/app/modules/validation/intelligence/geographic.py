from __future__ import annotations

import pandas as pd

from app.models import DetectorConfig
from app.modules.sirl.profiler import ColumnRoles, json_safe
from app.modules.validation.intelligence.metrics import employment_rate, numeric_stats, series_missing_rate
from app.modules.validation.intelligence.registry import is_enabled, thresholds
from app.modules.validation.intelligence.types import (
    EMPLOYMENT_CANDIDATES,
    HOURS_CANDIDATES,
    INCOME_CANDIDATES,
    UNUSUAL_PATTERN,
    Detection,
    DetectorOutcome,
    first_column,
)


def _metric_block(subset: pd.DataFrame, emp: str | None, income: str | None, hours: str | None) -> dict:
    return {
        "n": int(len(subset)),
        "employment_rate": employment_rate(subset[emp] if emp else None),
        "missing_rate": series_missing_rate(subset),
        "income": numeric_stats(subset[income] if income else None),
        "hours": numeric_stats(subset[hours] if hours else None),
    }


def evaluate_geographic(
    frame: pd.DataFrame,
    roles: ColumnRoles,
    configs: dict[str, DetectorConfig],
) -> DetectorOutcome:
    if not roles.district_id and not roles.cluster_id:
        return DetectorOutcome(
            available=False, skipped=True, reason="district_code not present — geographic detector unavailable"
        )
    emp = first_column(list(frame.columns), EMPLOYMENT_CANDIDATES)
    income = first_column(list(frame.columns), INCOME_CANDIDATES)
    hours = first_column(list(frame.columns), HOURS_CANDIDATES)
    national = _metric_block(frame, emp, income, hours)
    detections: list[Detection] = []

    if is_enabled(configs, "GEOGRAPHIC_DISTRICT") and roles.district_id:
        cfg = thresholds(configs, "GEOGRAPHIC_DISTRICT")
        min_n = int(cfg.get("min_records", 8))
        pp = float(cfg.get("pp_threshold", 0.2))
        for district, subset in frame.groupby(roles.district_id, dropna=True):
            metrics = _metric_block(subset, emp, income, hours)
            if metrics["n"] < min_n or metrics["employment_rate"] is None or national["employment_rate"] is None:
                continue
            delta = metrics["employment_rate"] - national["employment_rate"]
            if abs(delta) >= pp:
                detections.append(
                    Detection(
                        entity_type="district",
                        entity_id=str(district),
                        detector_type="GEOGRAPHIC_DISTRICT",
                        category="GEOGRAPHIC",
                        classification=UNUSUAL_PATTERN,
                        severity="HIGH" if abs(delta) >= 0.3 else "MEDIUM",
                        explanation="District employment rate differs substantially from the national/batch baseline.",
                        district_id=str(district),
                        field_name="employment_rate",
                        observed_value=json_safe(metrics["employment_rate"]),
                        expected_value=json_safe(national["employment_rate"]),
                        deviation=json_safe(delta),
                        baseline_type="national",
                        evidence={"n_records": metrics["n"], "peer_comparison": "unavailable"},
                    )
                )

    if is_enabled(configs, "GEOGRAPHIC_CLUSTER") and roles.cluster_id:
        cfg = thresholds(configs, "GEOGRAPHIC_CLUSTER")
        min_n = int(cfg.get("min_records", 6))
        pp = float(cfg.get("pp_threshold", 0.25))
        for cluster, subset in frame.groupby(roles.cluster_id, dropna=True):
            metrics = _metric_block(subset, emp, income, hours)
            if metrics["n"] < min_n or metrics["employment_rate"] is None:
                continue
            district = None
            district_emp = national["employment_rate"]
            baseline_type = "national"
            if roles.district_id and roles.district_id in subset.columns and not subset[roles.district_id].dropna().empty:
                district = str(subset[roles.district_id].dropna().iloc[0])
                parent = frame.loc[frame[roles.district_id].astype(str) == district]
                district_emp = employment_rate(parent[emp] if emp else None)
                baseline_type = "district"
            baseline = district_emp if district_emp is not None else national["employment_rate"]
            if baseline is None:
                continue
            delta = metrics["employment_rate"] - baseline
            if abs(delta) >= pp:
                detections.append(
                    Detection(
                        entity_type="cluster",
                        entity_id=str(cluster),
                        detector_type="GEOGRAPHIC_CLUSTER",
                        category="GEOGRAPHIC",
                        classification=UNUSUAL_PATTERN,
                        severity="HIGH" if abs(delta) >= 0.35 else "MEDIUM",
                        explanation="Cluster employment distribution differs substantially from its parent geography.",
                        cluster_id=str(cluster),
                        district_id=district,
                        field_name="employment_rate",
                        observed_value=json_safe(metrics["employment_rate"]),
                        expected_value=json_safe(baseline),
                        deviation=json_safe(delta),
                        baseline_type=baseline_type,
                        evidence={"n_records": metrics["n"], "national_employment_rate": json_safe(national["employment_rate"])},
                    )
                )
    if not detections and len(frame) < 8:
        return DetectorOutcome(available=False, skipped=True, reason="INSUFFICIENT_DATA for geographic comparison")
    return DetectorOutcome(available=True, detections=detections)
