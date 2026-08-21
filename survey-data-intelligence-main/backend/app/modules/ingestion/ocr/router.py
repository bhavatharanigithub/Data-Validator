from __future__ import annotations

import json
import tempfile
from pathlib import Path
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.modules.ingestion.errors import IngestError
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.ingestion.ocr.constants import SUPPORTED_EXTENSIONS, SUPPORTED_IMAGE_EXTENSIONS
from app.modules.ingestion.ocr.normalizer import NormalizedRecord, normalize_records
from app.modules.ingestion.ocr.ocr_engine import (
    OcrEngineError,
    extract_from_image,
    extract_from_pdf,
)
from app.modules.ingestion.ocr.parser import parse_ocr_lines
from app.modules.ingestion.ocr.schemas import (
    OcrImportRequest,
    OcrImportResponse,
    OcrPreviewResponse,
    OcrRecordOut,
)
from app.modules.ingestion.standardizer import standardize
from app.modules.pipeline.service import queue_pipeline_for_batch
from app.modules.storage.persist import persist_standardized_result

router = APIRouter(prefix="/ingest/ocr", tags=["ingest", "ocr"])


def _safe_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in SUPPORTED_EXTENSIONS else ""


def _record_to_out(rec: NormalizedRecord) -> OcrRecordOut:
    payload = rec.as_dict()
    return OcrRecordOut(
        **payload,
        needs_review=rec.needs_review,
        issues=rec.issues,
        warnings=rec.warnings,
        field_confidence=rec.field_confidence,
        field_confidence_band=rec.field_confidence_band,
        record_confidence=rec.record_confidence,
        record_confidence_band=rec.record_confidence_band,
    )


@router.post("/preview", response_model=OcrPreviewResponse)
def preview_ocr(file: UploadFile = File(...)) -> OcrPreviewResponse:
    filename = file.filename or "upload"
    suffix = _safe_suffix(filename)
    if not suffix:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Allowed: PDF, JPG, JPEG, PNG, WEBP, BMP.",
        )

    # This endpoint is intentionally synchronous so FastAPI runs the CPU-heavy
    # PaddleOCR/PyMuPDF work in its threadpool instead of blocking the
    # Uvicorn event loop while the Next.js frontend waits for the response.
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    max_upload_bytes = settings.ocr_max_upload_mb * 1024 * 1024
    if len(content) > max_upload_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds the {settings.ocr_max_upload_mb} MB upload limit.",
        )

    log_event("ocr_ingestion_started", filename=filename, size_bytes=len(content))

    with tempfile.TemporaryDirectory(prefix="ocr_upload_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        # Filenames are never reused verbatim for on-disk paths; isolates
        # the upload from the rest of the project filesystem (FEATURE 20).
        upload_path = tmp_dir / f"{uuid4().hex}{suffix}"
        upload_path.write_bytes(content)

        try:
            if suffix in SUPPORTED_IMAGE_EXTENSIONS:
                page_results = extract_from_image(upload_path)
            else:
                page_results = extract_from_pdf(upload_path, tmp_dir)
        except OcrEngineError as exc:
            log_failure("ocr_ingestion_failure", filename=filename, error=exc.message)
            raise HTTPException(status_code=422, detail=exc.message) from exc
        except Exception as exc:  # pragma: no cover - defensive
            log_failure("ocr_ingestion_failure", filename=filename, error="unexpected")
            raise HTTPException(
                status_code=500, detail="OCR processing failed unexpectedly."
            ) from exc
        # upload_path and any rendered page images are removed automatically
        # when the TemporaryDirectory context exits (FEATURE 20).

    all_lines = [line for page in page_results for line in page.lines]
    if not all_lines:
        raise HTTPException(
            status_code=422,
            detail="No text could be detected in the uploaded file.",
        )

    raw_records = parse_ocr_lines(all_lines)
    if not raw_records:
        raise HTTPException(
            status_code=422,
            detail="Text was detected, but no survey records could be identified. "
            "Records must contain a recognizable 'Record ID' field.",
        )

    normalized = normalize_records(raw_records)
    records_out = [_record_to_out(rec) for rec in normalized]
    raw_text = "\n".join(line.text for line in all_lines)

    log_event(
        "ocr_ingestion_preview_completed",
        filename=filename,
        pages=len(page_results),
        records_detected=len(records_out),
    )

    return OcrPreviewResponse(
        success=True,
        filename=filename,
        pages=len(page_results),
        records_detected=len(records_out),
        records=records_out,
        records_needing_review=sum(1 for r in records_out if r.needs_review),
        raw_text=raw_text,
    )


@router.post("/import", response_model=OcrImportResponse)
def import_ocr(body: OcrImportRequest, db: Session = Depends(get_db)) -> OcrImportResponse:
    rows = [r.model_dump(exclude={"page"}) for r in body.records]
    frame = pd.DataFrame.from_records(rows)
    if frame.empty:
        raise HTTPException(status_code=400, detail="No records to import.")

    try:
        result = standardize(frame)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="OCR records could not be standardized.") from exc

    try:
        stored = persist_standardized_result(db, result, "photo_pdf")
    except IngestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    # Best-effort ingestion metadata sidecar (original filename + per-record
    # page numbers). Never written into the analytical Parquet columns, so
    # it can't confuse the rules/statistics/ML engines downstream.
    try:
        meta_path = Path(settings.data_dir) / "processed" / f"{stored.batch_id}.ocr_meta.json"
        meta_path.write_text(
            json.dumps(
                {
                    "source": "photo_pdf",
                    "original_filename": body.filename,
                    "pages": [r.page for r in body.records],
                },
                default=str,
            )
        )
    except OSError:
        log_failure("ocr_metadata_write_failed", batch_id=stored.batch_id)

    records_requiring_review = sum(1 for r in body.records if not r.record_id)

    pipeline = queue_pipeline_for_batch(db, stored.batch_id)
    db.expire_all()
    status = pipeline.status
    if status in {"PENDING", "RUNNING"}:
        status = "QUEUED"

    log_event(
        "ocr_ingestion_imported",
        batch_id=stored.batch_id,
        rows=stored.records,
        filename=body.filename,
    )

    return OcrImportResponse(
        batch_id=stored.batch_id,
        rows=int(result.frame.shape[0]),
        columns=result.columns,
        schema_version=result.schema_version,
        records_imported=int(result.frame.shape[0]),
        records_requiring_review=records_requiring_review,
        status=status,
        pipeline_run_id=pipeline.pipeline_run_id,
        reused=pipeline.reused,
        success=True,
    )
