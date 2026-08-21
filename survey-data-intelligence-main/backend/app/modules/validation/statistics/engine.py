from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Batch, BatchStatus, ValidationRun
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.sirl.profiler import detect_roles
from app.modules.sirl.repositories import load_context
from app.modules.storage.parquet import ParquetStorage
from app.modules.validation.errors import ValidationError
from app.modules.validation.statistics.baselines import (
    eligible_variables,
    load_historical_baselines,
    load_thresholds,
)
from app.modules.validation.statistics.detectors import (
    detect_group_z_score,
    detect_historical_shift,
    detect_iqr,
    detect_z_score,
)
from app.modules.validation.statistics.repository import persist_evidence, replace_statistics_runs
from app.modules.validation.statistics.schemas import StatisticsRunResponse

_INGESTED = {BatchStatus.COMPLETED, BatchStatus.PROFILED}


def _require_batch(db: Session, batch_id: str) -> Batch:
    batch = db.scalars(select(Batch).where(Batch.batch_id == batch_id)).first()
    if batch is None:
        raise ValidationError("batch not found", status_code=404)
    if batch.status not in _INGESTED:
        raise ValidationError("batch ingestion is not COMPLETED", status_code=409)
    return batch


def _id_series(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if not column or column not in frame.columns:
        return pd.Series([None] * len(frame), index=frame.index)
    return frame[column].map(lambda value: None if pd.isna(value) else str(value))


def evaluate_statistics(
    frame: pd.DataFrame,
    variables: list[str],
    roles,
    thresholds,
    historical: dict,
) -> list[dict]:
    record_ids = _id_series(frame, roles.record_id)
    enumerator_ids = _id_series(frame, roles.enumerator_id)
    cluster_ids = _id_series(frame, roles.cluster_id)
    district_ids = _id_series(frame, roles.district_id)
    detections: list[dict] = []
    current_means: dict[str, float] = {}
    ids = {
        "record_ids": record_ids,
        "enumerator_ids": enumerator_ids,
        "cluster_ids": cluster_ids,
        "district_ids": district_ids,
    }
    for variable in variables:
        numeric = pd.to_numeric(frame[variable], errors="coerce")
        valid = numeric.dropna()
        if not valid.empty:
            current_means[variable] = float(valid.mean())
        detections.extend(detect_z_score(numeric, variable=variable, thresholds=thresholds, **ids))
        detections.extend(detect_iqr(numeric, variable=variable, thresholds=thresholds, **ids))
        if roles.enumerator_id:
            detections.extend(
                detect_group_z_score(
                    frame,
                    numeric,
                    variable=variable,
                    group_col=roles.enumerator_id,
                    scope="enumerator",
                    thresholds=thresholds,
                    **ids,
                )
            )
        if roles.cluster_id:
            detections.extend(
                detect_group_z_score(
                    frame,
                    numeric,
                    variable=variable,
                    group_col=roles.cluster_id,
                    scope="cluster",
                    thresholds=thresholds,
                    **ids,
                )
            )
        if roles.district_id:
            detections.extend(
                detect_group_z_score(
                    frame,
                    numeric,
                    variable=variable,
                    group_col=roles.district_id,
                    scope="district",
                    thresholds=thresholds,
                    **ids,
                )
            )
    detections.extend(detect_historical_shift(current_means, historical, thresholds))
    return detections


def run_statistics(
    db: Session,
    batch_id: str,
    storage: ParquetStorage | None = None,
) -> StatisticsRunResponse:
    _require_batch(db, batch_id)
    store = storage or ParquetStorage()
    if not store.exists(batch_id):
        raise ValidationError("parquet file was not found for batch", status_code=404)

    log_event("statistical_validation_started", batch_id=batch_id)
    replace_statistics_runs(db, batch_id)
    started = datetime.now(UTC)
    run = ValidationRun(
        batch_id=batch_id,
        validation_type="statistics",
        status="RUNNING",
        started_at=started,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        frame = store.read(batch_id)
        roles = detect_roles(frame)
        sirl_context = load_context(db, batch_id)
        variables = eligible_variables(frame, roles, sirl_context)
        thresholds = load_thresholds()
        historical, historical_available = load_historical_baselines(db, batch_id, variables)
        detections = evaluate_statistics(frame, variables, roles, thresholds, historical)
        persist_evidence(db, run.id, batch_id, detections)
        run.status = "COMPLETED"
        run.rules_evaluated = len(variables)
        run.records_checked = int(frame.shape[0])
        run.violation_count = len(detections)
        run.skipped_rules_json = {
            "historical_context_available": historical_available,
            "engine": "statistics",
        }
        run.completed_at = datetime.now(UTC)
        db.commit()
    except ValidationError:
        run.status = "FAILED"
        run.completed_at = datetime.now(UTC)
        db.commit()
        log_failure("statistical_validation_failed", batch_id=batch_id)
        raise
    except Exception as exc:
        run.status = "FAILED"
        run.completed_at = datetime.now(UTC)
        db.commit()
        log_failure("statistical_validation_failed", batch_id=batch_id)
        raise ValidationError("statistical validation failed", status_code=500) from exc

    log_event(
        "statistical_validation_completed",
        batch_id=batch_id,
        detections=run.violation_count,
        variables_checked=run.rules_evaluated,
    )
    return _summary(run, detections, historical_available=historical_available)


def _summary(
    run: ValidationRun,
    detections: list[dict],
    historical_available: bool,
) -> StatisticsRunResponse:
    def count(level: str) -> int:
        return sum(1 for item in detections if item["severity"] == level)

    meta = run.skipped_rules_json if isinstance(run.skipped_rules_json, dict) else {}
    available = bool(meta.get("historical_context_available", historical_available))
    return StatisticsRunResponse(
        success=run.status == "COMPLETED",
        batch_id=run.batch_id,
        validation_run_id=run.id,
        status=run.status,
        records_checked=run.records_checked,
        variables_checked=run.rules_evaluated,
        detections=run.violation_count,
        critical=count("CRITICAL"),
        high=count("HIGH"),
        medium=count("MEDIUM"),
        low=count("LOW"),
        historical_context_available=available,
    )
