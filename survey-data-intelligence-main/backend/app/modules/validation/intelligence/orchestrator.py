from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Batch, BatchStatus, HistoricalProfile, ValidationRun
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.sirl.profiler import detect_roles
from app.modules.storage.parquet import ParquetStorage
from app.modules.validation.errors import ValidationError
from app.modules.validation.intelligence.enumerator import evaluate_enumerators
from app.modules.validation.intelligence.geographic import evaluate_geographic
from app.modules.validation.intelligence.historical import evaluate_distribution_shift
from app.modules.validation.intelligence.patterns import evaluate_patterns
from app.modules.validation.intelligence.registry import enabled_map
from app.modules.validation.intelligence.relationships import evaluate_relationships
from app.modules.validation.intelligence.repository import persist_detections, replace_intelligence_runs
from app.modules.validation.intelligence.schemas import IntelligenceRunResponse
from app.modules.validation.intelligence.temporal import evaluate_temporal
from app.modules.validation.intelligence.types import Detection, DetectorOutcome

_INGESTED = {BatchStatus.COMPLETED, BatchStatus.PROFILED}


def _require_batch(db: Session, batch_id: str) -> Batch:
    batch = db.scalars(select(Batch).where(Batch.batch_id == batch_id)).first()
    if batch is None:
        raise ValidationError("batch not found", status_code=404)
    if batch.status not in _INGESTED:
        raise ValidationError("batch ingestion is not COMPLETED", status_code=409)
    return batch


def run_intelligence(db: Session, batch_id: str, storage: ParquetStorage | None = None) -> IntelligenceRunResponse:
    _require_batch(db, batch_id)
    store = storage or ParquetStorage()
    if not store.exists(batch_id):
        raise ValidationError("parquet file was not found for batch", status_code=404)
    log_event("intelligence_validation_started", batch_id=batch_id)
    replace_intelligence_runs(db, batch_id)
    run = ValidationRun(
        batch_id=batch_id,
        validation_type="intelligence",
        status="RUNNING",
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        frame = store.read(batch_id)
        roles = detect_roles(frame)
        configs = enabled_map(db)
        historical = list(
            db.scalars(
                select(HistoricalProfile).where(HistoricalProfile.batch_id != batch_id)
            ).all()
        )
        outcomes: dict[str, DetectorOutcome] = {
            "RELATIONSHIP": evaluate_relationships(frame, roles, configs),
            "ENUMERATOR": evaluate_enumerators(frame, roles, configs, historical),
            "TEMPORAL": evaluate_temporal(frame, roles, configs),
            "GEOGRAPHIC": evaluate_geographic(frame, roles, configs),
            "PATTERN": evaluate_patterns(frame, roles, configs),
            "HISTORICAL": evaluate_distribution_shift(db, batch_id, frame, roles, configs),
        }
        detections: list[Detection] = []
        available = []
        skipped = []
        reasons: dict[str, str] = {}
        for name, outcome in outcomes.items():
            if outcome.available and not outcome.skipped:
                available.append(name)
                detections.extend(outcome.detections)
            else:
                skipped.append(name)
                if outcome.reason:
                    reasons[name] = outcome.reason
        persist_detections(db, run.id, batch_id, detections)
        run.status = "COMPLETED"
        run.records_checked = int(frame.shape[0])
        run.violation_count = len(detections)
        run.rules_evaluated = len(available)
        run.skipped_rules_json = {
            "engine": "intelligence",
            "available": available,
            "skipped": skipped,
            "reason": reasons,
            "detectors_failed": [],
        }
        run.completed_at = datetime.now(UTC)
        db.commit()
    except ValidationError:
        run.status = "FAILED"
        run.completed_at = datetime.now(UTC)
        db.commit()
        log_failure("intelligence_validation_failed", batch_id=batch_id)
        raise
    except Exception as exc:
        run.status = "FAILED"
        run.completed_at = datetime.now(UTC)
        db.commit()
        log_failure("intelligence_validation_failed", batch_id=batch_id)
        raise ValidationError("intelligence validation failed", status_code=500) from exc
    log_event("intelligence_validation_completed", batch_id=batch_id, detections=run.violation_count)
    meta = run.skipped_rules_json if isinstance(run.skipped_rules_json, dict) else {}
    return IntelligenceRunResponse(
        success=True,
        batch_id=batch_id,
        validation_run_id=run.id,
        status=run.status,
        records_checked=run.records_checked,
        detections=run.violation_count,
        available=list(meta.get("available") or []),
        skipped=list(meta.get("skipped") or []),
        reason=dict(meta.get("reason") or {}),
    )
