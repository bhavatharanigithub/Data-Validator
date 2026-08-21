from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DetectorConfig, VariableProfile
from app.modules.sirl.profiler import ColumnRoles, json_safe
from app.modules.validation.intelligence.metrics import categorical_tvd
from app.modules.validation.intelligence.registry import is_enabled, thresholds
from app.modules.validation.intelligence.types import UNUSUAL_PATTERN, Detection, DetectorOutcome

import pandas as pd


def evaluate_distribution_shift(
    db: Session,
    batch_id: str,
    frame: pd.DataFrame,
    roles: ColumnRoles,
    configs: dict[str, DetectorConfig],
) -> DetectorOutcome:
    del roles
    if not is_enabled(configs, "DISTRIBUTION_SHIFT"):
        return DetectorOutcome(available=False, skipped=True, reason="DISTRIBUTION_SHIFT disabled")
    prior = list(
        db.scalars(
            select(VariableProfile)
            .where(VariableProfile.batch_id != batch_id)
            .order_by(VariableProfile.id.desc())
        ).all()
    )
    if not prior:
        return DetectorOutcome(
            available=False, skipped=True, reason="INSUFFICIENT HISTORICAL DATA — no prior variable profiles"
        )
    latest_batch = prior[0].batch_id
    prior_vars = {row.variable_name: row for row in prior if row.batch_id == latest_batch}
    cfg = thresholds(configs, "DISTRIBUTION_SHIFT")
    detections: list[Detection] = []
    for column in frame.columns:
        previous = prior_vars.get(column)
        if previous is None:
            continue
        payload = previous.profile_json or {}
        kind = payload.get("kind") or previous.kind
        if kind != "categorical":
            continue
        expected = {
            str(item.get("value")): int(item.get("count") or 0)
            for item in payload.get("top_values") or []
        }
        if not expected:
            expected = {str(k): int(v) for k, v in (payload.get("value_frequencies") or {}).items()}
        actual_counts = frame[column].dropna().astype(str).value_counts().to_dict()
        actual = {str(k): int(v) for k, v in actual_counts.items()}
        if sum(expected.values()) < 8 or sum(actual.values()) < 8:
            continue
        distance = categorical_tvd(expected, actual)
        if distance >= float(cfg.get("tvd_threshold", 0.35)):
            detections.append(
                Detection(
                    entity_type="district",
                    entity_id=batch_id,
                    detector_type="DISTRIBUTION_SHIFT",
                    category="HISTORICAL",
                    classification=UNUSUAL_PATTERN,
                    severity="MEDIUM",
                    explanation="Categorical distribution differs substantially from the prior batch profile.",
                    field_name=column,
                    observed_value=json_safe(distance),
                    expected_value=float(cfg.get("tvd_threshold", 0.35)),
                    deviation=json_safe(distance),
                    baseline_type="historical_batch",
                    evidence={"metric": "total_variation_distance", "source_batch_id": latest_batch},
                )
            )
    return DetectorOutcome(available=True, detections=detections)
