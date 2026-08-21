from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.modules.validation.errors import ValidationError
from app.modules.validation.explanation.schemas import (
    ExplanationBatchResponse,
    ExplanationRecordResponse,
    ExplanationRunRequest,
)
from app.modules.validation.explanation.service import explain_batch, explain_record, get_record_explanation

router = APIRouter(prefix="/validation", tags=["validation-explanation"])


def _raise(exc: ValidationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/explanations/run/{batch_id}", response_model=ExplanationBatchResponse)
def run_batch_explanations(
    batch_id: str,
    payload: ExplanationRunRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> ExplanationBatchResponse:
    try:
        return explain_batch(db, batch_id, request=payload)
    except ValidationError as exc:
        _raise(exc)
        raise


@router.post("/explanations/{batch_id}/{record_id}", response_model=ExplanationRecordResponse)
def run_record_explanation(
    batch_id: str,
    record_id: str,
    db: Session = Depends(get_db),
    force: bool = Query(False),
) -> ExplanationRecordResponse:
    try:
        return explain_record(db, batch_id, record_id, force=force)
    except ValidationError as exc:
        _raise(exc)
        raise


@router.get("/explanations/{batch_id}/{record_id}", response_model=ExplanationRecordResponse)
def read_record_explanation(
    batch_id: str, record_id: str, db: Session = Depends(get_db)
) -> ExplanationRecordResponse:
    try:
        return get_record_explanation(db, batch_id, record_id)
    except ValidationError as exc:
        _raise(exc)
        raise
