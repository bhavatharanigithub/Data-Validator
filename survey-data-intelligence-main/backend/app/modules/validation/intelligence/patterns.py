from __future__ import annotations

import pandas as pd

from app.models import DetectorConfig
from app.modules.sirl.profiler import ColumnRoles, json_safe
from app.modules.validation.intelligence.metrics import signature
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


def _fields(frame: pd.DataFrame) -> list[str]:
    columns = list(frame.columns)
    return [
        col
        for col in [
            first_column(columns, AGE_CANDIDATES),
            first_column(columns, SEX_CANDIDATES),
            first_column(columns, EDUCATION_CANDIDATES),
            first_column(columns, EMPLOYMENT_CANDIDATES),
            first_column(columns, HOURS_CANDIDATES),
            first_column(columns, INCOME_CANDIDATES),
        ]
        if col
    ]


def evaluate_patterns(
    frame: pd.DataFrame,
    roles: ColumnRoles,
    configs: dict[str, DetectorConfig],
) -> DetectorOutcome:
    if not is_enabled(configs, "CLUSTER_PATTERN"):
        return DetectorOutcome(available=False, skipped=True, reason="CLUSTER_PATTERN disabled")
    if not roles.cluster_id:
        return DetectorOutcome(available=False, skipped=True, reason="cluster_id not present")
    fields = _fields(frame)
    if len(fields) < 3:
        return DetectorOutcome(available=False, skipped=True, reason="Too few canonical fields for signatures")
    cfg = thresholds(configs, "CLUSTER_PATTERN")
    min_n = int(cfg.get("min_records", 8))
    share_t = float(cfg.get("share_threshold", 0.7))
    detections: list[Detection] = []
    rec_col = roles.record_id
    for cluster, subset in frame.groupby(roles.cluster_id, dropna=True):
        n = int(len(subset))
        if n < min_n:
            continue
        records = subset.to_dict(orient="records")
        sigs = [signature(item, fields) for item in records]
        counts: dict[str, int] = {}
        for item in sigs:
            counts[item] = counts.get(item, 0) + 1
        top_sig, top_n = max(counts.items(), key=lambda pair: pair[1])
        share = top_n / n
        if share < share_t:
            continue
        example = next((item for item, sig in zip(records, sigs) if sig == top_sig), records[0])
        record_id = None if not rec_col else str(example.get(rec_col))
        detections.append(
            Detection(
                entity_type="cluster",
                entity_id=str(cluster),
                detector_type="CLUSTER_PATTERN",
                category="PATTERN",
                classification=UNUSUAL_PATTERN,
                severity="MEDIUM",
                explanation="A high concentration of similar responses was detected within this cluster.",
                record_id=record_id,
                cluster_id=str(cluster),
                district_id=None if not roles.district_id else str(example.get(roles.district_id) or "") or None,
                enumerator_id=None if not roles.enumerator_id else str(example.get(roles.enumerator_id) or "") or None,
                field_name="response_signature",
                observed_value=json_safe(share),
                expected_value=share_t,
                deviation=json_safe(share - share_t),
                baseline_type="cluster_internal",
                evidence={
                    "duplicate_signature_count": int(top_n),
                    "near_duplicate_count": int(top_n),
                    "n_records": n,
                    "signature": top_sig,
                },
            )
        )
    return DetectorOutcome(available=True, detections=detections)
