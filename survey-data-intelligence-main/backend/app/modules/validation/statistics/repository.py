from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StatisticalEvidence, ValidationRun
from app.modules.validation.statistics.schemas import StatisticalEvidenceOut


def replace_statistics_runs(db: Session, batch_id: str) -> None:
    from app.modules.pipeline.preservation import protected_ids_for_replace

    protected = protected_ids_for_replace()
    runs = [
        run
        for run in db.scalars(
            select(ValidationRun).where(
                ValidationRun.batch_id == batch_id,
                ValidationRun.validation_type == "statistics",
            )
        ).all()
        if run.id not in protected
    ]
    run_ids = [run.id for run in runs]
    if run_ids:
        rows = db.scalars(
            select(StatisticalEvidence).where(StatisticalEvidence.validation_run_id.in_(run_ids))
        ).all()
        for row in rows:
            db.delete(row)
        for run in runs:
            db.delete(run)
    db.commit()


def persist_evidence(
    db: Session,
    run_id: int,
    batch_id: str,
    detections: list[dict],
) -> None:
    now = datetime.now(UTC)
    db.add_all(
        [
            StatisticalEvidence(
                validation_run_id=run_id,
                batch_id=batch_id,
                record_id=item.get("record_id"),
                enumerator_id=item.get("enumerator_id"),
                cluster_id=item.get("cluster_id"),
                district_id=item.get("district_id"),
                variable=item["variable"],
                detector=item["detector"],
                scope=item["scope"],
                observed_value=item.get("observed_value"),
                baseline_value=item.get("baseline_value"),
                baseline_std=item.get("baseline_std"),
                score=item.get("score"),
                threshold=item.get("threshold"),
                severity=item["severity"],
                evidence_json=item.get("evidence_json") or {},
                created_at=now,
            )
            for item in detections
        ]
    )


def list_evidence(db: Session, run_id: int) -> list[StatisticalEvidenceOut]:
    rows = db.scalars(
        select(StatisticalEvidence).where(StatisticalEvidence.validation_run_id == run_id)
    ).all()
    return [
        StatisticalEvidenceOut(
            record_id=row.record_id,
            enumerator_id=row.enumerator_id,
            cluster_id=row.cluster_id,
            district_id=row.district_id,
            variable=row.variable,
            detector=row.detector,
            scope=row.scope,
            observed_value=row.observed_value,
            baseline_value=row.baseline_value,
            baseline_std=row.baseline_std,
            score=row.score,
            threshold=row.threshold,
            severity=row.severity,
            evidence=row.evidence_json or {},
        )
        for row in rows
    ]
