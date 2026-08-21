from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Batch, BatchStatus, PipelineRun
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.pipeline.preservation import preserve_active_engine_runs
from app.modules.pipeline.repository import activate_pipeline_run, stage_row
from app.modules.sirl.errors import SirlError
from app.modules.sirl.service import profile_batch
from app.modules.storage.parquet import ParquetStorage
from app.modules.validation.errors import ValidationError
from app.modules.validation.explanation.schemas import ExplanationBatchResponse, ExplanationRunRequest
from app.modules.validation.explanation.service import explain_batch
from app.modules.validation.fusion.engine import run_fusion
from app.modules.validation.intelligence.orchestrator import run_intelligence
from app.modules.validation.ml.engine import run_ml
from app.modules.validation.rules.engine import run_rules
from app.modules.validation.statistics.engine import run_statistics

_INGESTED = {BatchStatus.COMPLETED, BatchStatus.PROFILED, BatchStatus.PROFILING, BatchStatus.PROFILE_FAILED}
_log = logging.getLogger("pipeline")


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_error(message: str) -> str:
    lowered = message.lower()
    if any(token in lowered for token in ("bearer ", "api_key", "sk-", "authorization")):
        return "stage failed"
    return message[:500]


def _duration_ms(started: datetime | None) -> int | None:
    if started is None:
        return None
    now = _now()
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return int((now - started).total_seconds() * 1000)


def _mark(
    db: Session,
    run: PipelineRun,
    stage: str,
    *,
    status: str,
    engine_run_id: int | None = None,
    records: int | None = None,
    error: str | None = None,
    detail: dict | None = None,
) -> None:
    row = stage_row(db, run.id, stage)
    now = _now()
    if status == "PROCESSING":
        row.started_at = row.started_at or now
        row.status = "PROCESSING"
        run.current_stage = stage
        if run.started_at is None:
            run.started_at = now
            run.status = "RUNNING"
        _log.info(
            "PIPELINE run=%s batch=%s stage=%s status=STARTED",
            run.id,
            run.batch_id,
            stage,
        )
    else:
        row.status = status
        row.completed_at = now
        row.engine_run_id = engine_run_id
        row.records_processed = records
        row.error = error
        row.detail_json = detail or row.detail_json
        duration = _duration_ms(row.started_at)
        _log.info(
            "PIPELINE run=%s batch=%s stage=%s status=%s records=%s duration_ms=%s",
            run.id,
            run.batch_id,
            stage,
            status,
            records,
            duration,
        )
    db.commit()


def _already_done(db: Session, run: PipelineRun, stage: str) -> bool:
    return stage_row(db, run.id, stage).status in {"COMPLETED", "SKIPPED", "UNAVAILABLE"}


def explanation_stage_status(explained: ExplanationBatchResponse) -> tuple[str, bool]:
    """Return (stage_status, explanation_unavailable). Never leave PROCESSING."""
    if explained.records_explained == 0 or explained.available > 0:
        return "COMPLETED", False
    return "UNAVAILABLE", True


def _recoverable(exc: Exception) -> bool:
    text = str(exc).lower()
    tokens = ("timeout", "temporar", "connection", "unavailable", "429", "503", "502")
    return any(token in text for token in tokens)


def _fail(db: Session, run: PipelineRun, stage: str, message: str, error_code: str = "PIPELINE_ERROR") -> None:
    text = _safe_error(message)
    _mark(db, run, stage, status="FAILED", error=text)
    run.status = "FAILED"
    run.error_stage = stage
    run.error_code = error_code
    run.error_message = text
    run.completed_at = _now()
    run.current_stage = stage
    run.is_active = False
    db.commit()
    log_failure("pipeline_failed", batch_id=run.batch_id, stage=stage)


def execute_pipeline(db: Session, run: PipelineRun, batch: Batch) -> None:
    with preserve_active_engine_runs(db, batch.batch_id):
        _execute_pipeline(db, run, batch)


def _execute_pipeline(db: Session, run: PipelineRun, batch: Batch) -> None:
    store = ParquetStorage()
    run.status = "RUNNING"
    run.started_at = run.started_at or _now()
    db.commit()

    ingest_ok = batch.status in _INGESTED or batch.status == BatchStatus.COMPLETED
    if not _already_done(db, run, "INGESTION"):
        _mark(
            db,
            run,
            "INGESTION",
            status="COMPLETED" if ingest_ok else "FAILED",
            records=batch.records,
            detail={"batch_status": batch.status, "source": batch.source},
            error=None if ingest_ok else "batch ingestion is not COMPLETED",
        )
    if not ingest_ok:
        _fail(db, run, "INGESTION", "batch ingestion is not COMPLETED", "INVALID_INPUT")
        return

    parquet_ok = store.exists(batch.batch_id)
    if not _already_done(db, run, "PARQUET"):
        _mark(
            db,
            run,
            "PARQUET",
            status="COMPLETED" if parquet_ok else "FAILED",
            records=batch.records,
            detail={"path": batch.parquet_path},
            error=None if parquet_ok else "parquet file was not found for batch",
        )
    if not parquet_ok:
        _fail(db, run, "PARQUET", "parquet file was not found for batch", "PARQUET_FAILED")
        return

    call_order: list[str] = list((run.metadata_json or {}).get("call_order") or [])
    meta = dict(run.metadata_json or {})

    def record_order(name: str) -> None:
        if name not in call_order:
            call_order.append(name)
        meta["call_order"] = call_order
        run.metadata_json = meta
        db.commit()

    if not _already_done(db, run, "SIRL"):
        try:
            _mark(db, run, "SIRL", status="PROCESSING")
            record_order("SIRL")
            sirl = profile_batch(db, batch.batch_id, storage=store)
            _mark(
                db,
                run,
                "SIRL",
                status="COMPLETED",
                records=sirl.records,
                detail={"status": sirl.status, "reused_existing": sirl.reused_existing},
            )
        except SirlError as exc:
            _fail(db, run, "SIRL", exc.message, "SIRL_FAILED")
            return
        except Exception as exc:
            _fail(db, run, "SIRL", str(exc), "SIRL_FAILED")
            return

    if not _already_done(db, run, "RULES"):
        try:
            _mark(db, run, "RULES", status="PROCESSING")
            record_order("RULES")
            rules = run_rules(db, batch.batch_id, storage=store)
            _mark(
                db,
                run,
                "RULES",
                status="COMPLETED",
                engine_run_id=rules.validation_run_id,
                records=rules.records_checked,
                detail={"violations": rules.violations, "rules_evaluated": rules.rules_evaluated},
            )
        except ValidationError as exc:
            _fail(db, run, "RULES", exc.message, "RULES_FAILED")
            return
        except Exception as exc:
            _fail(db, run, "RULES", str(exc), "RULES_FAILED")
            return

    if not _already_done(db, run, "STATISTICS"):
        try:
            _mark(db, run, "STATISTICS", status="PROCESSING")
            record_order("STATISTICS")
            stats = run_statistics(db, batch.batch_id, storage=store)
            _mark(
                db,
                run,
                "STATISTICS",
                status="COMPLETED",
                engine_run_id=stats.validation_run_id,
                records=stats.records_checked,
                detail={"status": stats.status, "detections": stats.detections},
            )
        except ValidationError as exc:
            _fail(db, run, "STATISTICS", exc.message, "STATISTICS_FAILED")
            return
        except Exception as exc:
            _fail(db, run, "STATISTICS", str(exc), "STATISTICS_FAILED")
            return

    if not _already_done(db, run, "INTELLIGENCE"):
        try:
            _mark(db, run, "INTELLIGENCE", status="PROCESSING")
            record_order("INTELLIGENCE")
            intel = run_intelligence(db, batch.batch_id, storage=store)
            skipped = list(intel.skipped or [])
            intel_status = "COMPLETED"
            if intel.status != "COMPLETED" and not skipped:
                intel_status = "UNAVAILABLE"
            _mark(
                db,
                run,
                "INTELLIGENCE",
                status=intel_status,
                engine_run_id=intel.validation_run_id,
                records=intel.records_checked,
                detail={
                    "status": intel.status,
                    "available": intel.available,
                    "skipped": skipped,
                    "reason": intel.reason,
                    "detector_status": {name: "SKIPPED" for name in skipped},
                },
            )
        except ValidationError as exc:
            _mark(db, run, "INTELLIGENCE", status="UNAVAILABLE", error=_safe_error(exc.message))
        except Exception as exc:
            _mark(db, run, "INTELLIGENCE", status="UNAVAILABLE", error=_safe_error(str(exc)))

    ml_unavailable = stage_row(db, run.id, "ML").status == "UNAVAILABLE"
    if not _already_done(db, run, "ML"):
        try:
            _mark(db, run, "ML", status="PROCESSING")
            record_order("ML")
            ml = run_ml(db, batch.batch_id, storage=store)
            ml_ok = ml.status == "COMPLETED"
            ml_unavailable = not ml_ok
            _mark(
                db,
                run,
                "ML",
                status="COMPLETED" if ml_ok else "UNAVAILABLE",
                engine_run_id=ml.validation_run_id,
                records=ml.records_checked,
                detail={"status": ml.status, "training_source": ml.training_source},
            )
        except ValidationError as exc:
            _fail(db, run, "ML", exc.message, "ML_FAILED")
            return
        except Exception as exc:
            _fail(db, run, "ML", str(exc), "ML_FAILED")
            return

    if not _already_done(db, run, "FUSION"):
        try:
            _mark(db, run, "FUSION", status="PROCESSING")
            record_order("FUSION")
            fusion = run_fusion(db, batch.batch_id)
            if fusion.status != "COMPLETED":
                _mark(
                    db,
                    run,
                    "FUSION",
                    status="UNAVAILABLE",
                    engine_run_id=fusion.validation_run_id,
                    records=fusion.records_assessed,
                    detail={"status": fusion.status},
                )
                _fail(db, run, "FUSION", f"fusion status {fusion.status}", "FUSION_FAILED")
                return
            _mark(
                db,
                run,
                "FUSION",
                status="COMPLETED",
                engine_run_id=fusion.validation_run_id,
                records=fusion.records_assessed,
                detail={
                    "status": fusion.status,
                    "methodology_version": fusion.methodology_version,
                    "available_sources": fusion.available_sources,
                },
            )
            meta["methodology_version"] = fusion.methodology_version
            run.metadata_json = meta
            db.commit()
        except ValidationError as exc:
            _fail(db, run, "FUSION", exc.message, "FUSION_FAILED")
            return
        except Exception as exc:
            _fail(db, run, "FUSION", str(exc), "FUSION_FAILED")
            return

    explanation_unavailable = stage_row(db, run.id, "EXPLANATION").status == "UNAVAILABLE"
    if not _already_done(db, run, "EXPLANATION"):
        attempts = max(1, int(settings.max_stage_retries) + 1)
        for attempt in range(attempts):
            try:
                _mark(db, run, "EXPLANATION", status="PROCESSING")
                record_order("EXPLANATION")
                request = ExplanationRunRequest(
                    scope="detected",
                    limit=int(settings.ai_explanation_all_limit),
                )
                explained = explain_batch(db, batch.batch_id, request=request)
                status, explanation_unavailable = explanation_stage_status(explained)
                _mark(
                    db,
                    run,
                    "EXPLANATION",
                    status=status,
                    engine_run_id=explained.fusion_run_id,
                    records=explained.records_explained,
                    detail={
                        "available": explained.available,
                        "unavailable": explained.unavailable,
                        "skipped": explained.skipped,
                        "limit": explained.limit,
                    },
                )
                break
            except ValidationError as exc:
                _mark(db, run, "EXPLANATION", status="UNAVAILABLE", error=_safe_error(exc.message))
                explanation_unavailable = True
                break
            except Exception as exc:
                if attempt + 1 < attempts and _recoverable(exc):
                    time.sleep(0.05 * (attempt + 1))
                    continue
                _mark(db, run, "EXPLANATION", status="UNAVAILABLE", error=_safe_error(str(exc)))
                explanation_unavailable = True
                break

    intel_row = stage_row(db, run.id, "INTELLIGENCE")
    intel_partial = intel_row.status == "UNAVAILABLE"
    run.completed_at = _now()
    run.current_stage = "COMPLETED"
    if explanation_unavailable or ml_unavailable or intel_partial:
        run.status = "PARTIAL"
    else:
        run.status = "COMPLETED"
    db.commit()
    activate_pipeline_run(db, run)
    log_event(
        "pipeline_completed",
        batch_id=run.batch_id,
        pipeline_run_id=run.id,
        status=run.status,
    )
    _log.info(
        "PIPELINE run=%s batch=%s stage=COMPLETE status=%s",
        run.id,
        run.batch_id,
        run.status,
    )
