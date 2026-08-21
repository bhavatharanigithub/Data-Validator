from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Batch, PipelineRun
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.pipeline.jobs import enqueue_pipeline_run, use_sync_jobs
from app.modules.pipeline.orchestrator import _safe_error, execute_pipeline
from app.modules.pipeline.repository import create_pipeline_run, latest_pipeline_run, to_out
from app.modules.pipeline.schemas import PipelineRunOut
from app.modules.validation.errors import ValidationError


def _require_batch(db: Session, batch_id: str) -> Batch:
    batch = db.scalars(select(Batch).where(Batch.batch_id == batch_id)).first()
    if batch is None:
        raise ValidationError("batch not found", status_code=404)
    return batch


def _mark_queued(db: Session, run: PipelineRun) -> None:
    meta = dict(run.metadata_json or {})
    meta["queued"] = True
    meta["queued_at"] = datetime.now(UTC).isoformat()
    run.metadata_json = meta
    db.commit()


def start_pipeline(db: Session, batch_id: str, rerun: bool = False) -> tuple[PipelineRunOut, bool]:
    batch = _require_batch(db, batch_id)
    existing = latest_pipeline_run(db, batch_id)
    if existing is not None and not rerun:
        if existing.status in {"COMPLETED", "PARTIAL", "RUNNING"}:
            return to_out(db, existing, reused=True), False
        if existing.status == "PENDING":
            queued = bool((existing.metadata_json or {}).get("queued"))
            return to_out(db, existing, reused=queued), not queued
    run = create_pipeline_run(db, batch.batch_id)
    return to_out(db, run, reused=False), True


def queue_pipeline_for_batch(db: Session, batch_id: str, rerun: bool = False) -> PipelineRunOut:
    payload, started = start_pipeline(db, batch_id, rerun=rerun)
    if started:
        run = db.get(PipelineRun, payload.pipeline_run_id)
        if run is not None:
            _mark_queued(db, run)
        if use_sync_jobs():
            log_event(
                "PIPELINE_ENQUEUE",
                batch_id=batch_id,
                pipeline_run_id=payload.pipeline_run_id,
            )
            execute_pipeline_job(payload.pipeline_run_id, db=db)
        else:
            enqueue_pipeline_run(payload.pipeline_run_id, batch_id=batch_id)
        db.expire_all()
        run = db.get(PipelineRun, payload.pipeline_run_id)
        if run is not None:
            return to_out(db, run, reused=False)
    return payload


def execute_pipeline_job(pipeline_run_id: int, db: Session | None = None) -> None:
    owns_session = db is None
    if owns_session:
        db = SessionLocal()
    assert db is not None
    try:
        run = db.get(PipelineRun, pipeline_run_id)
        if run is None:
            return
        batch_id = run.batch_id
        if run.status in {"COMPLETED", "PARTIAL", "FAILED"}:
            return
        log_event(
            "PIPELINE_EXECUTION_STARTED",
            batch_id=batch_id,
            pipeline_run_id=pipeline_run_id,
        )
        batch = db.scalars(select(Batch).where(Batch.batch_id == run.batch_id)).first()
        if batch is None:
            run.status = "FAILED"
            run.error_stage = "INGESTION"
            run.error_code = "INVALID_INPUT"
            run.error_message = "batch not found"
            db.commit()
            log_failure(
                "PIPELINE_EXECUTION_FAILED",
                batch_id=batch_id,
                pipeline_run_id=pipeline_run_id,
                error_code="INVALID_INPUT",
            )
            return
        execute_pipeline(db, run, batch)
        run = db.get(PipelineRun, pipeline_run_id)
        if run is not None and run.status in {"RUNNING", "PENDING"}:
            run.status = "FAILED"
            run.error_code = "RECOVERABLE"
            run.error_message = "pipeline exited without a terminal status"
            run.error_stage = run.current_stage
            db.commit()
            log_failure(
                "PIPELINE_EXECUTION_FAILED",
                batch_id=batch_id,
                pipeline_run_id=pipeline_run_id,
                error_code="RECOVERABLE",
            )
            return
        if run is not None:
            log_event(
                "PIPELINE_EXECUTION_FINISHED",
                batch_id=batch_id,
                pipeline_run_id=pipeline_run_id,
                status=run.status,
            )
    except Exception as exc:
        run = db.get(PipelineRun, pipeline_run_id)
        if run is not None:
            run.status = "FAILED"
            run.error_code = "PIPELINE_ERROR"
            run.error_message = _safe_error(str(exc))[:500]
            db.commit()
            log_failure(
                "PIPELINE_EXECUTION_FAILED",
                batch_id=run.batch_id,
                pipeline_run_id=pipeline_run_id,
                error_code="PIPELINE_ERROR",
            )
    finally:
        if owns_session:
            db.close()
