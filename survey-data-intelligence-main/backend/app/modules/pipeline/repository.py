from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PipelineRun, PipelineStageRun
from app.modules.pipeline.schemas import PipelineRunOut, StageOut

STAGE_ORDER = [
    "INGESTION",
    "PARQUET",
    "SIRL",
    "RULES",
    "STATISTICS",
    "INTELLIGENCE",
    "ML",
    "FUSION",
    "EXPLANATION",
]


def latest_pipeline_run(db: Session, batch_id: str) -> PipelineRun | None:
    return db.scalars(
        select(PipelineRun).where(PipelineRun.batch_id == batch_id).order_by(PipelineRun.id.desc())
    ).first()


def active_pipeline_run(db: Session, batch_id: str) -> PipelineRun | None:
    return db.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.batch_id == batch_id,
            PipelineRun.is_active.is_(True),
        )
        .order_by(PipelineRun.id.desc())
    ).first()


def activate_pipeline_run(db: Session, run: PipelineRun) -> None:
    others = db.scalars(
        select(PipelineRun).where(
            PipelineRun.batch_id == run.batch_id,
            PipelineRun.is_active.is_(True),
            PipelineRun.id != run.id,
        )
    ).all()
    for other in others:
        other.is_active = False
        meta = dict(other.metadata_json or {})
        meta["superseded_by"] = run.id
        other.metadata_json = meta
    run.is_active = True
    db.commit()


def stage_completed(db: Session, pipeline_run_id: int, stage: str) -> bool:
    row = stage_row(db, pipeline_run_id, stage)
    return row.status == "COMPLETED"


def get_pipeline_run(db: Session, pipeline_run_id: int) -> PipelineRun | None:
    return db.get(PipelineRun, pipeline_run_id)


def list_stages(db: Session, pipeline_run_id: int) -> list[PipelineStageRun]:
    rows = db.scalars(
        select(PipelineStageRun)
        .where(PipelineStageRun.pipeline_run_id == pipeline_run_id)
        .order_by(PipelineStageRun.id.asc())
    ).all()
    return list(rows)


def create_pipeline_run(db: Session, batch_id: str) -> PipelineRun:
    now = datetime.now(UTC)
    run = PipelineRun(
        batch_id=batch_id,
        status="PENDING",
        current_stage="INGESTION",
        created_at=now,
        metadata_json={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    for name in STAGE_ORDER:
        db.add(
            PipelineStageRun(
                pipeline_run_id=run.id,
                stage=name,
                status="PENDING",
            )
        )
    db.commit()
    return run


def stage_row(db: Session, pipeline_run_id: int, stage: str) -> PipelineStageRun:
    row = db.scalars(
        select(PipelineStageRun).where(
            PipelineStageRun.pipeline_run_id == pipeline_run_id,
            PipelineStageRun.stage == stage,
        )
    ).first()
    if row is None:
        row = PipelineStageRun(pipeline_run_id=pipeline_run_id, stage=stage, status="PENDING")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def to_out(db: Session, run: PipelineRun, reused: bool = False) -> PipelineRunOut:
    stages = [
        StageOut(
            stage=row.stage,
            status=row.status,  # type: ignore[arg-type]
            started_at=row.started_at,
            completed_at=row.completed_at,
            error=row.error,
            engine_run_id=row.engine_run_id,
            records_processed=row.records_processed,
            detail=dict(row.detail_json or {}),
        )
        for row in list_stages(db, run.id)
    ]
    return PipelineRunOut(
        pipeline_run_id=run.id,
        batch_id=run.batch_id,
        status=run.status,  # type: ignore[arg-type]
        current_stage=run.current_stage,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error_stage=run.error_stage,
        error_code=run.error_code,
        error_message=run.error_message,
        is_active=bool(run.is_active),
        reused=reused,
        stages=stages,
        metadata=dict(run.metadata_json or {}),
    )


def stage_progress(db: Session, run: PipelineRun) -> int | None:
    rows = list_stages(db, run.id)
    if not rows:
        return None
    done = sum(1 for row in rows if row.status in {"COMPLETED", "SKIPPED", "UNAVAILABLE"})
    return int(round(100 * done / len(rows)))
