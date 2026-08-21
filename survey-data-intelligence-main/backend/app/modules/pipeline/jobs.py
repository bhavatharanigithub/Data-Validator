from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, datetime, timedelta

from app.config import settings
from app.modules.ingestion.logging_utils import log_event, log_failure

_log = logging.getLogger("pipeline.jobs")
_lock = threading.Lock()
_started = False
_stop = threading.Event()
_busy: set[int] = set()
_semaphore: threading.Semaphore | None = None
_poller: threading.Thread | None = None


def use_sync_jobs() -> bool:
    raw = os.getenv("PIPELINE_SYNC_JOBS", "").strip().lower()
    if raw in {"1", "true", "yes"}:
        return True
    if raw in {"0", "false", "no"}:
        return False
    return bool(settings.pipeline_sync_jobs)


def start_workers() -> None:
    """Start the in-process poller exactly once from FastAPI lifespan."""
    global _started, _semaphore, _poller
    if use_sync_jobs():
        log_event("PIPELINE_WORKER_READY", mode="sync", pid=os.getpid())
        return
    with _lock:
        if _started:
            return
        try:
            _stop.clear()
            workers = max(1, int(settings.max_concurrent_pipelines))
            _semaphore = threading.Semaphore(workers)
            _poller = threading.Thread(
                target=_poller_loop,
                name="pipeline-poller",
                daemon=True,
            )
            _poller.start()
            _started = True
        except Exception:
            _started = False
            _log.exception("PIPELINE_WORKER_START_FAILED pid=%s", os.getpid())
            raise
    log_event("PIPELINE_WORKER_STARTED", pid=os.getpid(), workers=max(1, int(settings.max_concurrent_pipelines)))
    log_event("PIPELINE_WORKER_READY", mode="async", pid=os.getpid())


def stop_workers() -> None:
    global _started, _poller
    _stop.set()
    with _lock:
        _started = False
        _poller = None


def enqueue_pipeline_run(pipeline_run_id: int, batch_id: str | None = None) -> None:
    from app.modules.pipeline.service import execute_pipeline_job

    log_event(
        "PIPELINE_ENQUEUE",
        batch_id=batch_id,
        pipeline_run_id=pipeline_run_id,
        pid=os.getpid(),
    )
    if use_sync_jobs():
        execute_pipeline_job(pipeline_run_id)
        return
    start_workers()
    _dispatch(pipeline_run_id, batch_id)


def _dispatch(pipeline_run_id: int, batch_id: str | None) -> None:
    with _lock:
        if pipeline_run_id in _busy:
            return
        _busy.add(pipeline_run_id)
    thread = threading.Thread(
        target=_run_job,
        args=(pipeline_run_id, batch_id),
        name=f"pipeline-job-{pipeline_run_id}",
        daemon=True,
    )
    thread.start()


def _run_job(pipeline_run_id: int, batch_id: str | None) -> None:
    from app.modules.pipeline.service import execute_pipeline_job

    semaphore = _semaphore or threading.Semaphore(1)
    semaphore.acquire()
    try:
        log_event(
            "PIPELINE_JOB_RECEIVED",
            batch_id=batch_id,
            pipeline_run_id=pipeline_run_id,
            pid=os.getpid(),
        )
        execute_pipeline_job(pipeline_run_id)
    except Exception:
        log_failure(
            "PIPELINE_EXECUTION_FAILED",
            batch_id=batch_id,
            pipeline_run_id=pipeline_run_id,
            pid=os.getpid(),
        )
        _log.exception(
            "PIPELINE_EXECUTION_FAILED batch_id=%s pipeline_run_id=%s",
            batch_id,
            pipeline_run_id,
        )
    finally:
        with _lock:
            _busy.discard(pipeline_run_id)
        semaphore.release()


def _poller_loop() -> None:
    log_event("PIPELINE_WORKER_STARTED", role="poller", pid=os.getpid())
    while not _stop.wait(1.0):
        try:
            fail_stalled_pending_runs()
            for run_id, batch_id in _pending_unclaimed():
                _dispatch(run_id, batch_id)
        except Exception:
            _log.exception("PIPELINE_POLLER_ERROR pid=%s", os.getpid())


def _pending_unclaimed() -> list[tuple[int, str]]:
    from app.db import SessionLocal
    from app.models import PipelineRun
    from sqlalchemy import select

    db = SessionLocal()
    try:
        rows = db.scalars(select(PipelineRun).where(PipelineRun.status == "PENDING")).all()
        found: list[tuple[int, str]] = []
        with _lock:
            busy = set(_busy)
        for run in rows:
            if run.id not in busy:
                found.append((run.id, run.batch_id))
        return found
    finally:
        db.close()


def fail_stalled_pending_runs() -> int:
    """Mark PENDING runs that were queued but never claimed."""
    from app.db import SessionLocal
    from app.models import PipelineRun
    from sqlalchemy import select

    stall_seconds = max(5, int(getattr(settings, "pipeline_queue_stall_seconds", 60)))
    cutoff = datetime.now(UTC) - timedelta(seconds=stall_seconds)
    marked = 0
    db = SessionLocal()
    try:
        running = db.scalars(select(PipelineRun).where(PipelineRun.status == "RUNNING")).first()
        pending = db.scalars(select(PipelineRun).where(PipelineRun.status == "PENDING")).all()
        with _lock:
            busy = set(_busy)
        for run in pending:
            if run.id in busy:
                continue
            if running is not None:
                continue
            queued_at = _queued_at(run)
            if queued_at is None or queued_at > cutoff:
                continue
            run.status = "FAILED"
            run.error_code = "QUEUE_STALLED"
            run.error_stage = run.current_stage or "INGESTION"
            run.error_message = "pipeline job was queued but never started"
            run.completed_at = datetime.now(UTC)
            run.is_active = False
            log_failure(
                "PIPELINE_QUEUE_STALLED",
                batch_id=run.batch_id,
                pipeline_run_id=run.id,
            )
            marked += 1
        if marked:
            db.commit()
    finally:
        db.close()
    return marked


def _queued_at(run) -> datetime | None:
    meta = run.metadata_json or {}
    raw = meta.get("queued_at")
    if isinstance(raw, str) and raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed
        except ValueError:
            pass
    created = run.created_at
    if created is None:
        return None
    if created.tzinfo is None:
        return created.replace(tzinfo=UTC)
    return created
