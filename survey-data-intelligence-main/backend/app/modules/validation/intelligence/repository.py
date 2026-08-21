from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import QualityDetection, ValidationRun
from app.modules.validation.intelligence.types import Detection


def replace_intelligence_runs(db: Session, batch_id: str) -> None:
    from app.modules.pipeline.preservation import protected_ids_for_replace

    protected = protected_ids_for_replace()
    runs = [
        run
        for run in db.scalars(
            select(ValidationRun).where(
                ValidationRun.batch_id == batch_id,
                ValidationRun.validation_type == "intelligence",
            )
        ).all()
        if run.id not in protected
    ]
    run_ids = [run.id for run in runs]
    if run_ids:
        rows = db.scalars(
            select(QualityDetection).where(QualityDetection.validation_run_id.in_(run_ids))
        ).all()
        for row in rows:
            db.delete(row)
        for run in runs:
            db.delete(run)
    db.commit()


def persist_detections(db: Session, run_id: int, batch_id: str, detections: list[Detection]) -> None:
    now = datetime.now(UTC)
    db.add_all(
        [
            QualityDetection(
                validation_run_id=run_id,
                batch_id=batch_id,
                entity_type=item.entity_type,
                entity_id=item.entity_id,
                record_id=item.record_id,
                enumerator_id=item.enumerator_id,
                cluster_id=item.cluster_id,
                district_id=item.district_id,
                household_id=item.household_id,
                detector_type=item.detector_type,
                category=item.category,
                classification=item.classification,
                severity=item.severity,
                confidence=item.confidence,
                review_required=item.review_required,
                field_name=item.field_name,
                observed_value=item.observed_value,
                expected_value=item.expected_value,
                deviation=item.deviation,
                baseline_type=item.baseline_type,
                explanation=item.explanation,
                evidence_json=item.evidence,
                created_at=now,
            )
            for item in detections
        ]
    )


def list_detections(db: Session, batch_id: str) -> list[QualityDetection]:
    run = db.scalars(
        select(ValidationRun)
        .where(
            ValidationRun.batch_id == batch_id,
            ValidationRun.validation_type == "intelligence",
        )
        .order_by(ValidationRun.id.desc())
    ).first()
    if run is None:
        return []
    return list(
        db.scalars(select(QualityDetection).where(QualityDetection.validation_run_id == run.id)).all()
    )
