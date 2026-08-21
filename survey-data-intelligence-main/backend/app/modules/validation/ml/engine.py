from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Batch, BatchStatus, ValidationRun
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.sirl.profiler import detect_roles, json_safe
from app.modules.sirl.repositories import load_context
from app.modules.storage.parquet import ParquetStorage
from app.modules.validation.errors import ValidationError
from app.modules.validation.ml.features import (
    apply_median_imputer,
    fit_median_imputer,
    load_ml_settings,
    select_ml_features,
)
from app.modules.validation.ml.model import (
    MODEL_TYPE,
    MODEL_VERSION,
    infer,
    ml_severity,
    model_configuration,
    train_isolation_forest,
)
from app.modules.validation.ml.reference import combine_reference, load_historical_frames
from app.modules.validation.ml.repository import persist_ml_evidence, replace_ml_runs
from app.modules.validation.ml.schemas import MlRunResponse

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


def _empty_run(
    run: ValidationRun,
    *,
    status: str,
    records_checked: int,
    feature_names: list[str],
    training_source: str,
    historical_available: bool,
    training_records: int,
    configuration: dict,
) -> MlRunResponse:
    run.status = status
    run.rules_evaluated = len(feature_names)
    run.records_checked = records_checked
    run.violation_count = 0
    run.skipped_rules_json = {
        "engine": "ml",
        "status": status,
        "feature_names": feature_names,
        "training_source": training_source,
        "historical_data_available": historical_available,
        "training_records": training_records,
        "model_configuration": configuration,
        "imputation": "median",
    }
    run.completed_at = datetime.now(UTC)
    return MlRunResponse(
        success=True,
        batch_id=run.batch_id,
        validation_run_id=run.id,
        status=status,
        records_checked=records_checked,
        features_used=len(feature_names),
        feature_names=feature_names,
        anomalies=0,
        training_source=training_source,
        historical_data_available=historical_available,
        training_records=training_records,
        model_configuration=configuration,
    )


def run_ml(
    db: Session,
    batch_id: str,
    storage: ParquetStorage | None = None,
) -> MlRunResponse:
    _require_batch(db, batch_id)
    store = storage or ParquetStorage()
    if not store.exists(batch_id):
        raise ValidationError("parquet file was not found for batch", status_code=404)

    log_event("ml_validation_started", batch_id=batch_id)
    replace_ml_runs(db, batch_id)
    started = datetime.now(UTC)
    run = ValidationRun(
        batch_id=batch_id,
        validation_type="ml",
        status="RUNNING",
        started_at=started,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    detections: list[dict] = []
    try:
        frame = store.read(batch_id)
        roles = detect_roles(frame)
        sirl_context = load_context(db, batch_id)
        settings = load_ml_settings()
        configuration = model_configuration(settings)
        features = select_ml_features(frame, roles, sirl_context)
        historical_frames = load_historical_frames(db, batch_id, store)
        historical_available = bool(historical_frames)

        if len(features) < settings.min_features:
            result = _empty_run(
                run,
                status="insufficient_features",
                records_checked=int(frame.shape[0]),
                feature_names=features,
                training_source="none",
                historical_available=historical_available,
                training_records=0,
                configuration=configuration,
            )
            db.commit()
            return result

        reference = combine_reference(historical_frames, features)
        training_source = "historical"
        if reference is None or len(reference) < settings.min_training_records:
            if int(frame.shape[0]) < settings.min_training_records:
                result = _empty_run(
                    run,
                    status="insufficient_data",
                    records_checked=int(frame.shape[0]),
                    feature_names=features,
                    training_source="none",
                    historical_available=historical_available,
                    training_records=int(len(reference) if reference is not None else 0),
                    configuration=configuration,
                )
                db.commit()
                return result
            reference = frame
            training_source = "current_batch"

        medians = fit_median_imputer(reference, features)
        X_train, train_features = apply_median_imputer(reference, features, medians)
        X_current, used_features = apply_median_imputer(frame, features, medians)
        if len(used_features) < settings.min_features or X_train.shape[0] < settings.min_training_records:
            result = _empty_run(
                run,
                status="insufficient_features"
                if len(used_features) < settings.min_features
                else "insufficient_data",
                records_checked=int(frame.shape[0]),
                feature_names=used_features,
                training_source=training_source,
                historical_available=historical_available,
                training_records=int(X_train.shape[0]),
                configuration=configuration,
            )
            db.commit()
            return result

        fitted = train_isolation_forest(X_train, settings)
        score_samples, scores, labels = infer(fitted, X_current)
        anomaly_mask = labels == -1
        if bool(np.any(anomaly_mask)):
            record_ids = _id_series(frame, roles.record_id)
            enumerator_ids = _id_series(frame, roles.enumerator_id)
            cluster_ids = _id_series(frame, roles.cluster_id)
            district_ids = _id_series(frame, roles.district_id)
            indices = frame.index[anomaly_mask]
            for index in indices:
                loc = int(frame.index.get_indexer([index])[0])
                score = float(scores[loc])
                raw = float(score_samples[loc])
                severity = ml_severity(score, settings)
                detections.append(
                    {
                        "record_id": record_ids.loc[index],
                        "enumerator_id": enumerator_ids.loc[index],
                        "cluster_id": cluster_ids.loc[index],
                        "district_id": district_ids.loc[index],
                        "model_type": MODEL_TYPE,
                        "model_version": MODEL_VERSION,
                        "feature_names": used_features,
                        "anomaly_score": score,
                        "raw_model_score": raw,
                        "prediction": "anomaly",
                        "severity": severity,
                        "training_source": training_source,
                        "training_records": int(X_train.shape[0]),
                        "evidence_json": {
                            "record_id": record_ids.loc[index],
                            "model_type": MODEL_TYPE,
                            "anomaly_score": json_safe(score),
                            "raw_model_score": json_safe(raw),
                            "prediction": "anomaly",
                            "severity": severity,
                            "feature_names": used_features,
                            "imputation": {"strategy": "median", "medians": medians},
                            "training_source": training_source,
                            "score_note": "0-100 relative Isolation Forest anomaly score; not a probability",
                        },
                    }
                )

        persist_ml_evidence(db, run.id, batch_id, detections)
        run.status = "COMPLETED"
        run.rules_evaluated = len(used_features)
        run.records_checked = int(frame.shape[0])
        run.violation_count = len(detections)
        run.skipped_rules_json = {
            "engine": "ml",
            "status": "COMPLETED",
            "feature_names": used_features,
            "training_source": training_source,
            "historical_data_available": historical_available,
            "training_records": int(X_train.shape[0]),
            "model_configuration": configuration,
            "imputation": {"strategy": "median", "medians": medians},
            "small_batch_note": (
                "Isolation Forest flags unusual multidimensional patterns. "
                "current_batch training on a small sample is relative isolation, not proof of invalidity. "
                "ML-only detections are review signals, not confirmed data-quality anomalies."
            ),
            "ml_alone_does_not_confirm_anomaly": True,
        }
        run.completed_at = datetime.now(UTC)
        db.commit()
    except ValidationError:
        run.status = "FAILED"
        run.completed_at = datetime.now(UTC)
        db.commit()
        log_failure("ml_validation_failed", batch_id=batch_id)
        raise
    except Exception as exc:
        run.status = "FAILED"
        run.completed_at = datetime.now(UTC)
        db.commit()
        log_failure("ml_validation_failed", batch_id=batch_id)
        raise ValidationError("ml validation failed", status_code=500) from exc

    log_event(
        "ml_validation_completed",
        batch_id=batch_id,
        anomalies=run.violation_count,
        features_used=run.rules_evaluated,
        training_source=training_source,
    )
    return _summary(run, detections)


def _summary(run: ValidationRun, detections: list[dict]) -> MlRunResponse:
    meta = run.skipped_rules_json if isinstance(run.skipped_rules_json, dict) else {}

    def count(level: str) -> int:
        return sum(1 for item in detections if item.get("severity") == level)

    return MlRunResponse(
        success=run.status in {"COMPLETED", "insufficient_data", "insufficient_features"},
        batch_id=run.batch_id,
        validation_run_id=run.id,
        status=str(meta.get("status") or run.status),
        records_checked=run.records_checked,
        features_used=run.rules_evaluated,
        feature_names=list(meta.get("feature_names") or []),
        anomalies=run.violation_count,
        high=count("HIGH"),
        medium=count("MEDIUM"),
        low=count("LOW"),
        training_source=str(meta.get("training_source") or "none"),
        historical_data_available=bool(meta.get("historical_data_available")),
        training_records=int(meta.get("training_records") or 0),
        model_configuration=dict(meta.get("model_configuration") or {}),
    )
