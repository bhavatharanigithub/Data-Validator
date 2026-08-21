from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Batch, BatchStatus, DatasetProfile
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.sirl.enrichment import enrich_profile
from app.modules.sirl.errors import SirlError
from app.modules.sirl.profiler import profile_frame
from app.modules.sirl.repositories import (
    delete_profiles,
    load_ai_enrichment,
    load_context,
    load_prior_historical,
    profile_counts,
    save_bundle,
)
from app.modules.sirl.schemas import ProfileRunResponse, SirlContext
from app.modules.storage.parquet import ParquetStorage

_PROFILE_ALLOWED = {
    BatchStatus.COMPLETED,
    BatchStatus.PROFILED,
    BatchStatus.PROFILE_FAILED,
    BatchStatus.PROFILING,
}


def _require_batch(db: Session, batch_id: str) -> Batch:
    batch = db.scalars(select(Batch).where(Batch.batch_id == batch_id)).first()
    if batch is None:
        raise SirlError("batch not found", status_code=404)
    return batch


def _run_response(db: Session, batch: Batch, reused: bool) -> ProfileRunResponse:
    counts = profile_counts(db, batch.batch_id)
    dataset = db.scalars(
        select(DatasetProfile).where(DatasetProfile.batch_id == batch.batch_id)
    ).first()
    historical = load_prior_historical(db, batch.batch_id, batch.schema_version)
    enrichment = load_ai_enrichment(db, batch.batch_id)
    return ProfileRunResponse(
        success=True,
        batch_id=batch.batch_id,
        status=batch.status,
        records=dataset.record_count if dataset else int(batch.records or 0),
        variables=counts.variables,
        profiles_created=counts,
        historical_context_available=bool(historical["historical_context_available"]),
        reused_existing=reused,
        ai_enrichment_status=enrichment.status,
        ai_enrichment_reason=enrichment.reason,
    )


def profile_batch(db: Session, batch_id: str, storage: ParquetStorage | None = None) -> ProfileRunResponse:
    batch = _require_batch(db, batch_id)
    if batch.status == BatchStatus.PROFILED:
        existing = db.scalars(
            select(DatasetProfile).where(DatasetProfile.batch_id == batch_id)
        ).first()
        if existing is not None:
            log_event("sirl_profile_reused", batch_id=batch_id)
            return _run_response(db, batch, reused=True)

    if batch.status not in _PROFILE_ALLOWED:
        raise SirlError(
            "batch ingestion is not COMPLETED",
            status_code=409,
        )

    store = storage or ParquetStorage()
    if not store.exists(batch_id):
        raise SirlError("parquet file was not found for batch", status_code=404)

    log_event("sirl_profile_started", batch_id=batch_id, source=batch.source)
    batch.status = BatchStatus.PROFILING
    db.commit()

    try:
        frame = store.read(batch_id)
        parquet_path = store.absolute_path(batch_id)
        parquet_bytes = parquet_path.stat().st_size if parquet_path.exists() else None
        historical = load_prior_historical(db, batch_id, batch.schema_version)
        bundle = profile_frame(frame, parquet_bytes=parquet_bytes, historical=historical)
        delete_profiles(db, batch_id)
        save_bundle(db, batch_id, batch.schema_version, bundle)
        batch.status = BatchStatus.PROFILED
        batch.error_message = None
        db.commit()
    except SirlError:
        batch.status = BatchStatus.PROFILE_FAILED
        batch.error_message = "SIRL profiling failed"
        db.commit()
        log_failure("sirl_profile_failed", batch_id=batch_id)
        raise
    except Exception as exc:
        batch.status = BatchStatus.PROFILE_FAILED
        batch.error_message = "SIRL profiling failed"
        db.commit()
        log_failure("sirl_profile_failed", batch_id=batch_id)
        raise SirlError("SIRL profiling failed", status_code=500) from exc

    log_event(
        "sirl_profile_completed",
        batch_id=batch_id,
        records=bundle.dataset["record_count"],
        variables=len(bundle.variables),
    )
    try:
        enrich_profile(db, batch_id)
    except Exception:
        log_failure("sirl_ai_unavailable", batch_id=batch_id, reason="provider_error")
    db.refresh(batch)
    return _run_response(db, batch, reused=False)


def get_context(db: Session, batch_id: str) -> SirlContext:
    _require_batch(db, batch_id)
    context = load_context(db, batch_id)
    if context is None:
        raise SirlError("profile not found for batch", status_code=404)
    return context
