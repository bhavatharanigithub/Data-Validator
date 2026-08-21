from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PipelineRun, PipelineStageRun
from app.modules.ingestion.logging_utils import log_event
from app.modules.pipeline.jobs import enqueue_pipeline_run


def recover_abandoned_runs(db: Session) -> None:
    """Never leave a run permanently RUNNING after process restart."""
    now = datetime.now(UTC)
    abandoned = db.scalars(
        select(PipelineRun).where(PipelineRun.status.in_(["RUNNING", "PROCESSING"]))
    ).all()
    for run in abandoned:
        stages = db.scalars(
            select(PipelineStageRun).where(PipelineStageRun.pipeline_run_id == run.id)
        ).all()
        for stage in stages:
            if stage.status == "PROCESSING":
                stage.status = "FAILED"
                stage.error = "process restarted before stage completed"
                stage.completed_at = now
        run.status = "FAILED"
        run.error_code = "RECOVERABLE"
        run.error_stage = run.current_stage or run.error_stage
        run.error_message = "pipeline interrupted by process restart"
        run.completed_at = now
        run.is_active = False
        log_event(
            "pipeline_recovered",
            batch_id=run.batch_id,
            pipeline_run_id=run.id,
            status="FAILED",
        )
    db.commit()

    pending = db.scalars(select(PipelineRun).where(PipelineRun.status == "PENDING")).all()
    if not pending:
        return
    from app.modules.pipeline.jobs import use_sync_jobs

    for run in pending:
        meta = dict(run.metadata_json or {})
        meta["queued"] = True
        meta.setdefault("queued_at", datetime.now(UTC).isoformat())
        run.metadata_json = meta
        db.commit()
        if use_sync_jobs():
            continue
        enqueue_pipeline_run(run.id, batch_id=run.batch_id)
