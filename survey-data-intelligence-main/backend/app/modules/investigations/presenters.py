from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Investigation, UnifiedRiskAssessment
from app.modules.investigations.schemas import AuditOut, InvestigationOut


def with_assessment(db: Session, row: Investigation) -> InvestigationOut:
    assessment = db.scalars(
        select(UnifiedRiskAssessment)
        .where(
            UnifiedRiskAssessment.batch_id == row.batch_id,
            UnifiedRiskAssessment.record_id == row.record_id,
        )
        .order_by(UnifiedRiskAssessment.id.desc())
    ).first()
    return InvestigationOut(
        id=row.id,
        batch_id=row.batch_id,
        record_id=row.record_id,
        validation_run_id=row.validation_run_id,
        assigned_to=row.assigned_to,
        status=row.status,
        priority=row.priority,
        action=row.action,
        supervisor_notes=row.supervisor_notes,
        finding=row.finding,
        action_taken=row.action_taken,
        final_classification=row.final_classification,
        created_by=row.created_by,
        enumerator_id=row.enumerator_id,
        district_id=row.district_id,
        risk_score=assessment.risk_score if assessment is not None else None,
        severity=assessment.severity if assessment is not None else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        resolved_at=row.resolved_at,
    )


def audit_out(row) -> AuditOut:
    return AuditOut(
        id=row.id,
        investigation_id=row.investigation_id,
        user_id=row.user_id,
        action=row.action,
        previous_status=row.previous_status,
        new_status=row.new_status,
        note=row.note,
        timestamp=row.timestamp,
    )
