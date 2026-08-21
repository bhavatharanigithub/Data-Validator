from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Batch, BatchStatus
from app.modules.ingestion.errors import IngestError
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.ingestion.standardizer import StandardizedResult
from app.modules.storage.parquet import ParquetStorage, ParquetStoreResult


def generate_batch_id(source: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y_%m_%d_%H%M%S")
    return f"BATCH_{stamp}_{source}_{uuid4().hex[:6]}"


def allocate_batch_id(
    db: Session, source: str, storage: ParquetStorage, attempts: int = 8
) -> str:
    """Never reuse a batch_id that already has a DB row or Parquet file."""
    for _ in range(attempts):
        candidate = generate_batch_id(source)
        if storage.exists(candidate):
            continue
        existing = db.scalars(select(Batch).where(Batch.batch_id == candidate)).first()
        if existing is not None:
            continue
        return candidate
    raise IngestError("could not allocate a unique batch_id", status_code=500)


def persist_standardized_result(
    db: Session,
    result: StandardizedResult,
    source: str,
    storage: ParquetStorage | None = None,
    batch_id: str | None = None,
    input_hash: str | None = None,
) -> ParquetStoreResult:
    """Write Parquet and record batch metadata. Shared by CSV and eSIGMA."""
    store = storage or ParquetStorage()
    allocated = batch_id or allocate_batch_id(db, source, store)
    existing = db.scalars(select(Batch).where(Batch.batch_id == allocated)).first()
    if store.exists(allocated) or existing is not None:
        allocated = allocate_batch_id(db, source, store)

    batch = Batch(
        batch_id=allocated,
        source=source,
        survey_code="DEMO",
        status=BatchStatus.RECEIVED,
        schema_version=result.schema_version,
        records=int(result.frame.shape[0]),
        column_count=int(result.frame.shape[1]),
        created_at=datetime.now(UTC),
        input_hash=input_hash,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    batch.status = BatchStatus.PROCESSING
    db.commit()

    try:
        stored = store.write(result.frame, allocated)
    except Exception as exc:
        batch.status = BatchStatus.FAILED
        batch.error_message = (
            exc.message if isinstance(exc, IngestError) else "Parquet storage failed"
        )
        batch.completed_at = datetime.now(UTC)
        db.commit()
        log_failure("ingestion_failure", source=source, batch_id=allocated)
        if isinstance(exc, IngestError):
            raise
        raise IngestError("Parquet storage failed", status_code=500) from exc

    batch.status = BatchStatus.COMPLETED
    batch.parquet_path = stored.path
    batch.records = stored.records
    batch.column_count = stored.columns
    batch.completed_at = datetime.now(UTC)
    batch.error_message = None
    db.commit()
    db.refresh(batch)

    log_event(
        "ingestion_completed",
        source=source,
        batch_id=allocated,
        rows=stored.records,
        columns=stored.columns,
        storage=stored.storage,
    )
    return stored
