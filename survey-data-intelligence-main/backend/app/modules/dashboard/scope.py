"""Read-only current-batch vs cumulative query helpers.

Records are batch-scoped (batch_id + record_id). Enumerator, cluster, and district
codes on fused assessments are treated as global identities and may be merged
across batches. Each batch contributes only its latest fusion / intelligence run
so re-runs are not double-counted.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import QualityDetection, UnifiedRiskAssessment, ValidationRun
from app.modules.validation.fusion.classification import hydrate_assessment_rule_codes

VIEW_CURRENT = "current_batch"
VIEW_CUMULATIVE = "cumulative"
NO_CUMULATIVE_MESSAGE = "No processed batches available for cumulative analysis."
CUMULATIVE_LABEL = "Cumulative — All Batches"


def normalize_view(value: str | None) -> str:
    raw = str(value or VIEW_CURRENT).strip().lower().replace("-", "_")
    if raw in {VIEW_CUMULATIVE, "all", "all_batches", "cumulative_records"}:
        return VIEW_CUMULATIVE
    return VIEW_CURRENT


def is_cumulative(view: str | None) -> bool:
    return normalize_view(view) == VIEW_CUMULATIVE


def latest_run_ids(db: Session, validation_type: str) -> list[int]:
    rows = db.execute(
        select(ValidationRun.batch_id, func.max(ValidationRun.id))
        .where(ValidationRun.validation_type == validation_type)
        .group_by(ValidationRun.batch_id)
    ).all()
    return [int(run_id) for _batch_id, run_id in rows if run_id is not None]


def fused_batch_ids(db: Session) -> list[str]:
    rows = db.execute(
        select(ValidationRun.batch_id, func.max(ValidationRun.id))
        .where(ValidationRun.validation_type == "fusion")
        .group_by(ValidationRun.batch_id)
    ).all()
    return [str(batch_id) for batch_id, run_id in rows if run_id is not None]


def assessments_for_view(
    db: Session,
    batch_id: str | None,
    view: str | None = VIEW_CURRENT,
) -> list[UnifiedRiskAssessment]:
    from app.modules.dashboard.service import get_batch, latest_run

    if is_cumulative(view):
        run_ids = latest_run_ids(db, "fusion")
        if not run_ids:
            return []
        rows = list(
            db.scalars(
                select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.validation_run_id.in_(run_ids))
            ).all()
        )
        hydrate_assessment_rule_codes(db, rows)
        return rows
    batch = get_batch(db, batch_id)
    if batch is None:
        return []
    fusion = latest_run(db, batch.batch_id, "fusion")
    if fusion is None:
        return []
    rows = list(
        db.scalars(select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.validation_run_id == fusion.id)).all()
    )
    hydrate_assessment_rule_codes(db, rows)
    return rows


def detections_for_view(db: Session, batch_id: str | None, view: str | None = VIEW_CURRENT) -> list[QualityDetection]:
    from app.modules.dashboard.service import get_batch
    from app.modules.validation.intelligence.repository import list_detections

    if is_cumulative(view):
        run_ids = latest_run_ids(db, "intelligence")
        if not run_ids:
            return []
        return list(
            db.scalars(select(QualityDetection).where(QualityDetection.validation_run_id.in_(run_ids))).all()
        )
    batch = get_batch(db, batch_id)
    if batch is None:
        return []
    return list_detections(db, batch.batch_id)


def fused_batch_count(db: Session) -> int:
    return len(fused_batch_ids(db))
