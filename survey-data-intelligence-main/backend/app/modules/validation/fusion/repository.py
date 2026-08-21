from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UnifiedDatasetAssessment, UnifiedRiskAssessment, ValidationRun
from app.modules.validation.fusion.schemas import DatasetAssessmentOut, UnifiedAssessmentOut


def replace_fusion_runs(db: Session, batch_id: str) -> None:
    from app.modules.pipeline.preservation import protected_ids_for_replace

    protected = protected_ids_for_replace()
    runs = [
        run
        for run in db.scalars(
            select(ValidationRun).where(
                ValidationRun.batch_id == batch_id,
                ValidationRun.validation_type == "fusion",
            )
        ).all()
        if run.id not in protected
    ]
    run_ids = [run.id for run in runs]
    if run_ids:
        records = db.scalars(
            select(UnifiedRiskAssessment).where(
                UnifiedRiskAssessment.validation_run_id.in_(run_ids)
            )
        ).all()
        datasets = db.scalars(
            select(UnifiedDatasetAssessment).where(
                UnifiedDatasetAssessment.validation_run_id.in_(run_ids)
            )
        ).all()
        for row in records:
            db.delete(row)
        for row in datasets:
            db.delete(row)
        for run in runs:
            db.delete(run)
    db.commit()


def persist_assessments(
    db: Session, run_id: int, batch_id: str, items: list[dict]
) -> None:
    now = datetime.now(UTC)
    db.add_all(
        [
            UnifiedRiskAssessment(
                validation_run_id=run_id,
                batch_id=batch_id,
                record_id=item["record_id"],
                enumerator_id=item.get("enumerator_id"),
                cluster_id=item.get("cluster_id"),
                district_id=item.get("district_id"),
                risk_score=item["risk_score"],
                severity=item["severity"],
                confidence=item["confidence"],
                agreement=item["agreement"],
                available_sources_json=item["available_sources"],
                missing_sources_json=item["missing_sources"],
                source_scores_json=item["source_scores"],
                source_severities_json=item["source_severities"],
                escalation_applied=item["escalation_applied"],
                escalation_reason=item.get("escalation_reason"),
                methodology_version=item["methodology_version"],
                evidence_refs_json=item.get("evidence_refs") or {},
                anomaly_status=item.get("anomaly_status") or "NORMAL",
                classification_reason=item.get("classification_reason"),
                intelligence_classification=item.get("intelligence_classification"),
                primary_detector=item.get("primary_detector"),
                detector_count=item.get("detector_count"),
                review_required=bool(item.get("review_required")),
                created_at=now,
            )
            for item in items
        ]
    )


def persist_dataset_assessment(
    db: Session, run_id: int, batch_id: str, payload: dict | None
) -> None:
    if payload is None:
        return
    db.add(
        UnifiedDatasetAssessment(
            validation_run_id=run_id,
            batch_id=batch_id,
            context_score=payload["context_score"],
            severity=payload["severity"],
            evidence_confidence=payload["evidence_confidence"],
            agreement=payload.get("agreement") or "single_source",
            statistical_evidence_ids_json=payload.get("statistical_evidence_ids") or [],
            methodology_version=payload["methodology_version"],
            created_at=datetime.now(UTC),
        )
    )


def list_assessments(db: Session, run_id: int) -> list[UnifiedAssessmentOut]:
    rows = db.scalars(
        select(UnifiedRiskAssessment).where(
            UnifiedRiskAssessment.validation_run_id == run_id
        )
    ).all()
    return [
        UnifiedAssessmentOut(
            record_id=row.record_id,
            enumerator_id=row.enumerator_id,
            cluster_id=row.cluster_id,
            district_id=row.district_id,
            risk_score=row.risk_score,
            severity=row.severity,
            confidence=row.confidence,
            evidence_confidence=row.confidence,
            agreement=row.agreement,
            available_sources=list(row.available_sources_json or []),
            missing_sources=list(row.missing_sources_json or []),
            source_scores=dict(row.source_scores_json or {}),
            source_severities=dict(row.source_severities_json or {}),
            escalation_applied=bool(row.escalation_applied),
            escalation_reason=row.escalation_reason,
            methodology_version=row.methodology_version,
            evidence_refs=dict(row.evidence_refs_json or {}),
            anomaly_status=row.anomaly_status or "NORMAL",
            classification_reason=row.classification_reason,
            anomaly_reason=row.classification_reason,
        )
        for row in rows
    ]


def get_dataset_assessment(db: Session, run_id: int, batch_id: str) -> DatasetAssessmentOut | None:
    row = db.scalars(
        select(UnifiedDatasetAssessment).where(
            UnifiedDatasetAssessment.validation_run_id == run_id
        )
    ).first()
    if row is None:
        return None
    return DatasetAssessmentOut(
        batch_id=batch_id,
        validation_run_id=run_id,
        context_score=row.context_score,
        severity=row.severity,
        confidence=row.evidence_confidence,
        evidence_confidence=row.evidence_confidence,
        agreement=row.agreement,
        statistical_evidence_ids=list(row.statistical_evidence_ids_json or []),
        methodology_version=row.methodology_version,
        not_a_record_risk=True,
    )
