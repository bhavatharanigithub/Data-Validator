from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Batch
from app.modules.ingestion.csv_ingest import ingest_csv_bytes
from app.modules.ingestion.errors import IngestError
from app.modules.ingestion.schemas import ESigmaIngestRequest, IngestResponse
from app.modules.ingestion.service import ingest_from_esigma
from app.modules.ingestion.standardizer import StandardizedResult
from app.modules.pipeline.repository import latest_pipeline_run
from app.modules.pipeline.service import queue_pipeline_for_batch
from app.modules.storage.parquet import ParquetStoreResult
from app.modules.storage.persist import persist_standardized_result

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _find_by_hash(db: Session, digest: str) -> Batch | None:
    return db.scalars(
        select(Batch).where(Batch.input_hash == digest).order_by(Batch.id.desc())
    ).first()


def _to_response(
    result: StandardizedResult,
    stored: ParquetStoreResult,
    source: str,
    *,
    status: str = "QUEUED",
    pipeline_run_id: int | None = None,
    reused: bool = False,
) -> IngestResponse:
    return IngestResponse(
        success=True,
        source=source,  # type: ignore[arg-type]
        rows=int(result.frame.shape[0]),
        columns=result.columns,
        batch_id=stored.batch_id,
        schema_version=result.schema_version,
        dtypes=result.dtypes,
        storage="parquet",
        parquet_path=stored.path,
        status=status,
        pipeline_run_id=pipeline_run_id,
        reused=reused,
    )


def _persist(
    db: Session, result: StandardizedResult, source: str, input_hash: str | None = None
) -> ParquetStoreResult:
    try:
        return persist_standardized_result(db, result, source, input_hash=input_hash)
    except IngestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _reuse_existing(db: Session, digest: str, result: StandardizedResult, source: str) -> IngestResponse | None:
    existing = _find_by_hash(db, digest)
    if existing is None or not existing.parquet_path:
        return None
    run = latest_pipeline_run(db, existing.batch_id)
    if run is not None and run.status in {"PENDING", "RUNNING"}:
        return IngestResponse(
            success=True,
            source=source,  # type: ignore[arg-type]
            rows=int(existing.records or result.frame.shape[0]),
            columns=result.columns,
            batch_id=existing.batch_id,
            schema_version=existing.schema_version or result.schema_version,
            dtypes=result.dtypes,
            storage="parquet",
            parquet_path=existing.parquet_path,
            status="QUEUED" if run.status == "PENDING" else "RUNNING",
            pipeline_run_id=run.id,
            reused=True,
        )
    if settings.ingest_reuse_completed and run is not None and run.status in {"COMPLETED", "PARTIAL"}:
        return IngestResponse(
            success=True,
            source=source,  # type: ignore[arg-type]
            rows=int(existing.records or result.frame.shape[0]),
            columns=result.columns,
            batch_id=existing.batch_id,
            schema_version=existing.schema_version or result.schema_version,
            dtypes=result.dtypes,
            storage="parquet",
            parquet_path=existing.parquet_path,
            status=run.status,
            pipeline_run_id=run.id,
            reused=True,
        )
    return None


def _start_pipeline(db: Session, stored: ParquetStoreResult, result: StandardizedResult, source: str) -> IngestResponse:
    pipeline = queue_pipeline_for_batch(db, stored.batch_id)
    db.expire_all()
    status = pipeline.status
    if status in {"PENDING", "RUNNING"}:
        status = "QUEUED"
    return _to_response(
        result,
        stored,
        source,
        status=status,
        pipeline_run_id=pipeline.pipeline_run_id,
        reused=pipeline.reused,
    )


@router.post("/csv", response_model=IngestResponse)
async def ingest_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    auto_pipeline: bool = Query(True),
) -> IngestResponse:
    content = await file.read()
    digest = _hash_bytes(content)
    try:
        result = ingest_csv_bytes(content)
    except IngestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    reused = _reuse_existing(db, digest, result, "csv")
    if reused is not None:
        return reused
    stored = _persist(db, result, "csv", input_hash=digest)
    if not auto_pipeline:
        return _to_response(result, stored, "csv", status="INGESTED")
    return _start_pipeline(db, stored, result, "csv")


@router.post("/esigma", response_model=IngestResponse)
def ingest_esigma(
    body: ESigmaIngestRequest | None = None,
    db: Session = Depends(get_db),
    auto_pipeline: bool = Query(True),
) -> IngestResponse:
    path = body.path if body else None
    try:
        result = ingest_from_esigma(path=path)
    except IngestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    digest = _hash_bytes(json.dumps(result.frame.to_dict(orient="list"), sort_keys=True, default=str).encode())
    reused = _reuse_existing(db, digest, result, "esigma")
    if reused is not None:
        return reused
    stored = _persist(db, result, "esigma", input_hash=digest)
    if not auto_pipeline:
        return _to_response(result, stored, "esigma", status="INGESTED")
    return _start_pipeline(db, stored, result, "esigma")
