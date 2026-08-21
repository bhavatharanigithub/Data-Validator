from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Investigation, InvestigationAuditLog, UnifiedRiskAssessment, User
from app.modules.auth.deps import allowed_for_record, district_scope
from app.modules.investigations.constants import ACTION_STATUS, ACTIONS, PRIORITIES, RESOLVED, STATUSES
from app.modules.investigations.schemas import InvestigationCreate, InvestigationPatch, NoteCreate
from app.modules.validation.errors import ValidationError


def _now() -> datetime:
    return datetime.now(UTC)


def _assessment(db: Session, batch_id: str, record_id: str) -> UnifiedRiskAssessment | None:
    return db.scalars(
        select(UnifiedRiskAssessment)
        .where(
            UnifiedRiskAssessment.batch_id == batch_id,
            UnifiedRiskAssessment.record_id == record_id,
        )
        .order_by(UnifiedRiskAssessment.id.desc())
    ).first()


def _audit(
    db: Session,
    investigation: Investigation,
    user: User,
    action: str,
    *,
    previous: str | None,
    new: str | None,
    note: str | None,
) -> None:
    db.add(
        InvestigationAuditLog(
            investigation_id=investigation.id,
            user_id=user.username,
            action=action,
            previous_status=previous,
            new_status=new,
            note=note,
            timestamp=_now(),
        )
    )


def _priority_from_assessment(row: UnifiedRiskAssessment | None, requested: str | None) -> str:
    if requested in PRIORITIES:
        return requested
    if row is None:
        return "MEDIUM"
    if row.severity in PRIORITIES:
        return row.severity
    return "MEDIUM"


def require_visible(user: User, investigation: Investigation) -> None:
    if not allowed_for_record(user, district_id=investigation.district_id, cluster_id=None):
        raise ValidationError("investigation not found", status_code=404)


def get_investigation(db: Session, investigation_id: int, user: User) -> Investigation:
    row = db.get(Investigation, investigation_id)
    if row is None:
        raise ValidationError("investigation not found", status_code=404)
    require_visible(user, row)
    return row


def create_investigation(db: Session, payload: InvestigationCreate, user: User) -> Investigation:
    existing = db.scalars(
        select(Investigation).where(
            Investigation.batch_id == payload.batch_id,
            Investigation.record_id == payload.record_id,
        )
    ).first()
    if existing is not None:
        require_visible(user, existing)
        return existing
    assessment = _assessment(db, payload.batch_id, payload.record_id)
    if assessment is not None and not allowed_for_record(
        user, district_id=assessment.district_id, cluster_id=assessment.cluster_id
    ):
        raise ValidationError("record is outside assigned scope", status_code=403)
    row = Investigation(
        batch_id=payload.batch_id,
        record_id=payload.record_id,
        validation_run_id=payload.validation_run_id
        or (assessment.validation_run_id if assessment is not None else None),
        assigned_to=payload.assigned_to or user.username,
        status="OPEN",
        priority=_priority_from_assessment(assessment, payload.priority),
        created_by=user.username,
        enumerator_id=assessment.enumerator_id if assessment is not None else None,
        district_id=assessment.district_id if assessment is not None else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit(db, row, user, "CREATE", previous=None, new="OPEN", note=None)
    db.commit()
    db.refresh(row)
    return row


def list_investigations(
    db: Session,
    user: User,
    *,
    status: str | None = None,
    priority: str | None = None,
    enumerator: str | None = None,
    district: str | None = None,
    assigned_to: str | None = None,
    batch_id: str | None = None,
    record_id: str | None = None,
) -> tuple[list[Investigation], dict[str, int]]:
    query = select(Investigation)
    scoped = district_scope(user)
    if scoped is not None:
        query = query.where(Investigation.district_id.in_(scoped))
    if status:
        query = query.where(Investigation.status == status)
    if priority:
        query = query.where(Investigation.priority == priority)
    if enumerator:
        query = query.where(Investigation.enumerator_id == enumerator)
    if district:
        query = query.where(Investigation.district_id == district)
    if assigned_to:
        query = query.where(Investigation.assigned_to == assigned_to)
    if batch_id:
        query = query.where(Investigation.batch_id == batch_id)
    if record_id:
        query = query.where(Investigation.record_id == record_id)
    rows = list(db.scalars(query.order_by(Investigation.updated_at.desc())).all())
    counts = {
        "OPEN": 0,
        "IN_REVIEW": 0,
        "REQUIRES_REENUMERATION": 0,
        "ESCALATED": 0,
        "RESOLVED_VALID": 0,
        "RESOLVED_INVALID": 0,
        "resolved": 0,
    }
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
        if row.status in RESOLVED:
            counts["resolved"] += 1
    return rows, counts


def patch_investigation(db: Session, investigation_id: int, payload: InvestigationPatch, user: User) -> Investigation:
    row = get_investigation(db, investigation_id, user)
    previous = row.status
    action = payload.action
    new_status = payload.status
    if action is not None:
        if action not in ACTIONS:
            raise ValidationError("invalid investigation action", status_code=422)
        new_status = ACTION_STATUS[action]
        row.action = action
    if new_status is not None:
        if new_status not in STATUSES:
            raise ValidationError("invalid investigation status", status_code=422)
        row.status = new_status
        if new_status in RESOLVED:
            row.resolved_at = row.resolved_at or _now()
        else:
            row.resolved_at = None
    if payload.priority is not None:
        if payload.priority not in PRIORITIES:
            raise ValidationError("invalid investigation priority", status_code=422)
        row.priority = payload.priority
    if payload.assigned_to is not None:
        row.assigned_to = payload.assigned_to
    if payload.supervisor_notes is not None:
        row.supervisor_notes = payload.supervisor_notes
    if payload.finding is not None:
        row.finding = payload.finding
    if payload.action_taken is not None:
        row.action_taken = payload.action_taken
    if payload.final_classification is not None:
        row.final_classification = payload.final_classification
    row.updated_at = _now()
    note = payload.supervisor_notes
    audit_action = action or "UPDATE"
    _audit(db, row, user, audit_action, previous=previous, new=row.status, note=note)
    db.commit()
    db.refresh(row)
    return row


def add_note(db: Session, investigation_id: int, payload: NoteCreate, user: User) -> Investigation:
    row = get_investigation(db, investigation_id, user)
    row.supervisor_notes = payload.note
    row.updated_at = _now()
    _audit(db, row, user, "ADD_NOTE", previous=row.status, new=row.status, note=payload.note)
    db.commit()
    db.refresh(row)
    return row


def list_audit(db: Session, investigation_id: int, user: User) -> list[InvestigationAuditLog]:
    get_investigation(db, investigation_id, user)
    return list(
        db.scalars(
            select(InvestigationAuditLog)
            .where(InvestigationAuditLog.investigation_id == investigation_id)
            .order_by(InvestigationAuditLog.timestamp.asc(), InvestigationAuditLog.id.asc())
        ).all()
    )
