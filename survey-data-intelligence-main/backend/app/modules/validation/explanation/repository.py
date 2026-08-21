from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AiExplanation
from app.modules.validation.explanation.schemas import ExplanationBlock, ExplanationPayload


def display_status(row: AiExplanation | None, *, detected: bool | None = None) -> str:
    if detected is False:
        return "not_required"
    if row is None:
        return "not_generated"
    if row.status == "generating":
        return "generating"
    if row.status == "available":
        return "available"
    return "unavailable"


def get_explanation(db: Session, batch_id: str, record_id: str) -> AiExplanation | None:
    return db.scalars(
        select(AiExplanation).where(
            AiExplanation.batch_id == batch_id,
            AiExplanation.record_id == record_id,
        )
    ).first()


def delete_explanations_for_batch(db: Session, batch_id: str) -> None:
    rows = db.scalars(select(AiExplanation).where(AiExplanation.batch_id == batch_id)).all()
    for row in rows:
        db.delete(row)
    db.commit()


def upsert_explanation(
    db: Session,
    *,
    batch_id: str,
    record_id: str,
    validation_run_id: int,
    status: str,
    reason: str | None,
    model: str | None,
    payload: ExplanationPayload | None,
    context_hash: str | None,
) -> AiExplanation:
    explanation_json = payload.model_dump() if payload is not None else {}
    row = get_explanation(db, batch_id, record_id)
    now = datetime.now(UTC)
    if row is None:
        row = AiExplanation(
            batch_id=batch_id,
            record_id=record_id,
            validation_run_id=validation_run_id,
            status=status,
            reason=reason,
            model=model,
            explanation_json=explanation_json,
            context_hash=context_hash,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.validation_run_id = validation_run_id
        row.status = status
        row.reason = reason
        row.model = model
        row.explanation_json = explanation_json
        row.context_hash = context_hash
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return row


def to_block(row: AiExplanation | None) -> ExplanationBlock:
    if row is None:
        return ExplanationBlock(status="not_required", reason="no_review_signal")
    payload = row.explanation_json or {}
    return ExplanationBlock(
        status=row.status,
        reason=row.reason,
        model=row.model,
        primary_reason=payload.get("primary_reason"),
        secondary_reason=payload.get("secondary_reason"),
        summary=payload.get("summary"),
        what_it_means=payload.get("what_it_means") or payload.get("summary"),
        key_findings=list(payload.get("key_findings") or []),
        evidence_explanations=list(payload.get("evidence_explanations") or []),
        recommended_action=payload.get("recommended_action"),
        limitations=list(payload.get("limitations") or []),
        explanation_confidence=payload.get("explanation_confidence"),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
