from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Batch, UnifiedRiskAssessment
from app.modules.dashboard.service import dashboard_fusion_run
from app.modules.pipeline.repository import active_pipeline_run, latest_pipeline_run
from app.modules.storage.schemas import BatchListResponse, BatchResponse
from app.modules.validation.fusion.classification import is_confirmed_anomaly, anomaly_status_of

router = APIRouter(prefix="/batches", tags=["batches"])


def _to_response(db: Session, batch: Batch) -> BatchResponse:
    latest = latest_pipeline_run(db, batch.batch_id)
    active = active_pipeline_run(db, batch.batch_id)
    display = active or latest
    confirmed = None
    review = None
    version = None
    if display is not None:
        version = (display.metadata_json or {}).get("methodology_version")
        fusion = dashboard_fusion_run(db, batch.batch_id)
        if fusion is not None:
            rows = list(
                db.scalars(
                    select(UnifiedRiskAssessment).where(
                        UnifiedRiskAssessment.validation_run_id == fusion.id
                    )
                ).all()
            )
            confirmed = sum(1 for row in rows if is_confirmed_anomaly(row))
            review = sum(1 for row in rows if anomaly_status_of(row) == "REVIEW")
    return BatchResponse(
        batch_id=batch.batch_id,
        source=batch.source,
        status=batch.status,
        schema_version=batch.schema_version,
        records=batch.records,
        columns=batch.column_count,
        parquet_path=batch.parquet_path,
        created_at=batch.created_at,
        completed_at=batch.completed_at,
        error_message=batch.error_message,
        survey_code=batch.survey_code,
        pipeline_status=None if latest is None else latest.status,
        pipeline_run_id=None if display is None else display.id,
        pipeline_version=str(version) if version else None,
        confirmed_issues=confirmed,
        investigation_signals=review,
    )


@router.get("", response_model=BatchListResponse)
def list_batches(db: Session = Depends(get_db)) -> BatchListResponse:
    rows = db.scalars(select(Batch).order_by(Batch.created_at.desc()).limit(50)).all()
    return BatchListResponse(items=[_to_response(db, row) for row in rows])


@router.get("/{batch_id}", response_model=BatchResponse)
def get_batch(batch_id: str, db: Session = Depends(get_db)) -> BatchResponse:
    batch = db.scalars(select(Batch).where(Batch.batch_id == batch_id)).first()
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    return _to_response(db, batch)
