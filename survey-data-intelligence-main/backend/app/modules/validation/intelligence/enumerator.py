from __future__ import annotations

import pandas as pd

from app.models import DetectorConfig, HistoricalProfile
from app.modules.sirl.profiler import ColumnRoles, json_safe
from app.modules.validation.intelligence.metrics import (
    category_entropy,
    employment_rate,
    numeric_stats,
    series_missing_rate,
    signature,
)
from app.modules.validation.intelligence.registry import is_enabled, thresholds
from app.modules.validation.intelligence.types import (
    AGE_CANDIDATES,
    EDUCATION_CANDIDATES,
    EMPLOYMENT_CANDIDATES,
    HOURS_CANDIDATES,
    INCOME_CANDIDATES,
    SEX_CANDIDATES,
    UNUSUAL_PATTERN,
    Detection,
    DetectorOutcome,
    first_column,
)


def _profiles(frame: pd.DataFrame, roles: ColumnRoles) -> dict[str, dict]:
    if not roles.enumerator_id:
        return {}
    emp = first_column(list(frame.columns), EMPLOYMENT_CANDIDATES)
    hours = first_column(list(frame.columns), HOURS_CANDIDATES)
    income = first_column(list(frame.columns), INCOME_CANDIDATES)
    out: dict[str, dict] = {}
    for enum_id, subset in frame.groupby(roles.enumerator_id, dropna=True):
        out[str(enum_id)] = {
            "record_count": int(len(subset)),
            "employment_rate": employment_rate(subset[emp] if emp else None),
            "missing_rate": series_missing_rate(subset),
            "income": numeric_stats(subset[income] if income else None),
            "hours": numeric_stats(subset[hours] if hours else None),
            "entropy": category_entropy(subset[emp] if emp else None),
            "district_id": str(subset[roles.district_id].dropna().iloc[0])
            if roles.district_id and roles.district_id in subset.columns and not subset[roles.district_id].dropna().empty
            else None,
            "cluster_ids": sorted({str(v) for v in subset[roles.cluster_id].dropna().astype(str)})
            if roles.cluster_id
            else [],
            "subset": subset,
        }
    return out


def evaluate_enumerators(
    frame: pd.DataFrame,
    roles: ColumnRoles,
    configs: dict[str, DetectorConfig],
    historical_rows: list[HistoricalProfile] | None = None,
) -> DetectorOutcome:
    if not roles.enumerator_id:
        return DetectorOutcome(
            available=False, skipped=True, reason="enumerator_id not present — enumerator detection unavailable"
        )
    profiles = _profiles(frame, roles)
    if len(profiles) < 2:
        return DetectorOutcome(
            available=False, skipped=True, reason="INSUFFICIENT_DATA: fewer than two enumerators"
        )
    emp = first_column(list(frame.columns), EMPLOYMENT_CANDIDATES)
    batch_emp = employment_rate(frame[emp] if emp else None)
    batch_missing = series_missing_rate(frame)
    batch_entropy = category_entropy(frame[emp] if emp else None)
    detections: list[Detection] = []
    hist_by_enum: dict[str, dict] = {}
    for row in historical_rows or []:
        if row.grain == "enumerator":
            hist_by_enum[row.grain_key] = row.stats_json or {}

    for enum_id, profile in profiles.items():
        n = int(profile["record_count"])
        subset: pd.DataFrame = profile["subset"]
        district = profile["district_id"]
        district_emp = None
        if roles.district_id and district:
            district_emp = employment_rate(frame.loc[frame[roles.district_id].astype(str) == district, emp] if emp else None)

        def emit(detector: str, explanation: str, observed, expected, field: str, extra: dict, thresh: dict) -> None:
            if n < int(thresh.get("min_records", 8)):
                return
            detections.append(
                Detection(
                    entity_type="enumerator",
                    entity_id=enum_id,
                    detector_type=detector,
                    category="ENUMERATOR",
                    classification=UNUSUAL_PATTERN,
                    severity="MEDIUM",
                    explanation=explanation,
                    enumerator_id=enum_id,
                    district_id=district,
                    field_name=field,
                    observed_value=json_safe(observed),
                    expected_value=json_safe(expected),
                    deviation=json_safe(None if observed is None or expected is None else observed - expected),
                    baseline_type=extra.get("baseline_type", "batch"),
                    evidence={
                        "record_count": n,
                        "batch_employment_rate": json_safe(batch_emp),
                        "district_employment_rate": json_safe(district_emp),
                        **extra,
                    },
                )
            )

        if is_enabled(configs, "ENUMERATOR_DEVIATION") and batch_emp is not None and profile["employment_rate"] is not None:
            cfg = thresholds(configs, "ENUMERATOR_DEVIATION")
            baseline = district_emp if district_emp is not None else batch_emp
            baseline_type = "district" if district_emp is not None else "batch"
            delta = abs(profile["employment_rate"] - baseline)
            if delta >= float(cfg.get("pp_threshold", 0.25)):
                emit(
                    "ENUMERATOR_DEVIATION",
                    "Enumerator employment distribution differs substantially from the comparison baseline.",
                    profile["employment_rate"],
                    baseline,
                    "employment_rate",
                    {"baseline_type": baseline_type},
                    cfg,
                )
        if is_enabled(configs, "ENUMERATOR_MISSINGNESS"):
            cfg = thresholds(configs, "ENUMERATOR_MISSINGNESS")
            delta = abs(profile["missing_rate"] - batch_missing)
            if delta >= float(cfg.get("pp_threshold", 0.08)):
                emit(
                    "ENUMERATOR_MISSINGNESS",
                    "Enumerator missingness is unusually high or extremely low relative to the batch.",
                    profile["missing_rate"],
                    batch_missing,
                    "missing_rate",
                    {"baseline_type": "batch"},
                    cfg,
                )
        if is_enabled(configs, "ENUMERATOR_ENTROPY") and batch_entropy and profile["entropy"] is not None:
            cfg = thresholds(configs, "ENUMERATOR_ENTROPY")
            if batch_entropy > 0 and profile["entropy"] / batch_entropy <= float(cfg.get("entropy_ratio", 0.45)):
                emit(
                    "ENUMERATOR_ENTROPY",
                    "Enumerator categorical responses are unusually concentrated compared with the overall distribution.",
                    profile["entropy"],
                    batch_entropy,
                    "response_entropy",
                    {"baseline_type": "batch"},
                    cfg,
                )
        if is_enabled(configs, "PATTERN_ENUMERATOR_SIMILARITY"):
            cfg = thresholds(configs, "PATTERN_ENUMERATOR_SIMILARITY")
            fields = [
                col
                for col in [
                    first_column(list(frame.columns), AGE_CANDIDATES),
                    first_column(list(frame.columns), SEX_CANDIDATES),
                    first_column(list(frame.columns), EDUCATION_CANDIDATES),
                    emp,
                    first_column(list(frame.columns), HOURS_CANDIDATES),
                    first_column(list(frame.columns), INCOME_CANDIDATES),
                ]
                if col
            ]
            if n >= int(cfg.get("min_records", 8)) and fields:
                sigs = [signature(item, fields) for item in subset.to_dict(orient="records")]
                if sigs:
                    top = max(sigs.count(item) for item in set(sigs))
                    share = top / n
                    if share >= float(cfg.get("share_threshold", 0.6)):
                        emit(
                            "PATTERN_ENUMERATOR_SIMILARITY",
                            "Many records handled by this enumerator share nearly identical canonical response signatures.",
                            share,
                            float(cfg.get("share_threshold", 0.6)),
                            "response_similarity",
                            {"baseline_type": "enumerator_internal", "duplicate_signature_count": int(top)},
                            cfg,
                        )
        prior = hist_by_enum.get(enum_id) or {}
        prior_emp = (prior.get("employment_rate") if isinstance(prior, dict) else None) or (
            (prior.get("numeric_means") or {}).get("employment_rate") if isinstance(prior, dict) else None
        )
        if prior_emp is not None and profile["employment_rate"] is not None:
            if abs(float(prior_emp) - profile["employment_rate"]) >= 0.2:
                emit(
                    "ENUMERATOR_DEVIATION",
                    "Enumerator employment rate changed sharply versus historical behaviour for the same enumerator.",
                    profile["employment_rate"],
                    float(prior_emp),
                    "employment_rate",
                    {"baseline_type": "historical_enumerator"},
                    {"min_records": 1, "pp_threshold": 0.2},
                )
    return DetectorOutcome(available=True, detections=detections)
