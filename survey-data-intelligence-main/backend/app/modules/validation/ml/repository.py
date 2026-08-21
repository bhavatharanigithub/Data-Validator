from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MlEvidence, ValidationRun
from app.modules.validation.ml.schemas import MlEvidenceOut


def replace_ml_runs(db: Session, batch_id: str) -> None:
    from app.modules.pipeline.preservation import protected_ids_for_replace

    protected = protected_ids_for_replace()
    runs = [
        run
        for run in db.scalars(
            select(ValidationRun).where(
                ValidationRun.batch_id == batch_id,
                ValidationRun.validation_type == "ml",
            )
        ).all()
        if run.id not in protected
    ]
    run_ids = [run.id for run in runs]
    if run_ids:
        rows = db.scalars(select(MlEvidence).where(MlEvidence.validation_run_id.in_(run_ids))).all()
        for row in rows:
            db.delete(row)
        for run in runs:
            db.delete(run)
    db.commit()


def persist_ml_evidence(db: Session, run_id: int, batch_id: str, detections: list[dict]) -> None:
    now = datetime.now(UTC)
    db.add_all(
        [
            MlEvidence(
                validation_run_id=run_id,
                batch_id=batch_id,
                record_id=item.get("record_id"),
                enumerator_id=item.get("enumerator_id"),
                cluster_id=item.get("cluster_id"),
                district_id=item.get("district_id"),
                model_type=item["model_type"],
                model_version=item["model_version"],
                feature_names_json=item["feature_names"],
                anomaly_score=item["anomaly_score"],
                raw_model_score=item.get("raw_model_score"),
                prediction=item["prediction"],
                severity=item["severity"],
                training_source=item["training_source"],
                training_records=item["training_records"],
                evidence_json=item.get("evidence_json") or {},
                created_at=now,
            )
            for item in detections
        ]
    )


def list_ml_evidence(db: Session, run_id: int) -> list[MlEvidenceOut]:
    rows = db.scalars(select(MlEvidence).where(MlEvidence.validation_run_id == run_id)).all()
    return [
        MlEvidenceOut(
            record_id=row.record_id,
            enumerator_id=row.enumerator_id,
            cluster_id=row.cluster_id,
            district_id=row.district_id,
            model_type=row.model_type,
            model_version=row.model_version,
            feature_names=list(row.feature_names_json or []),
            anomaly_score=row.anomaly_score,
            raw_model_score=row.raw_model_score,
            prediction=row.prediction,
            severity=row.severity,
            training_source=row.training_source,
            training_records=row.training_records,
            evidence=row.evidence_json or {},
        )
        for row in rows
    ]
