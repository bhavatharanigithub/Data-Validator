from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.modules.pipeline.repository import (
    get_pipeline_run,
    latest_pipeline_run,
    stage_progress,
    to_out,
)
from app.modules.pipeline.schemas import PipelineRunOut, PipelineRunRequest, PipelineStatusLite
from app.modules.pipeline.service import queue_pipeline_for_batch
from app.modules.validation.errors import ValidationError

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _raise(exc: ValidationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/run/{batch_id}", response_model=PipelineRunOut)
def run_pipeline(
    batch_id: str,
    body: PipelineRunRequest | None = None,
    db: Session = Depends(get_db),
) -> PipelineRunOut:
    request = body or PipelineRunRequest()
    try:
        return queue_pipeline_for_batch(db, batch_id, rerun=request.rerun)
    except ValidationError as exc:
        _raise(exc)
        raise


@router.get("/batch/{batch_id}/status", response_model=PipelineStatusLite)
def read_pipeline_status(batch_id: str, db: Session = Depends(get_db)) -> PipelineStatusLite:
    run = latest_pipeline_run(db, batch_id)
    if run is None:
        raise HTTPException(status_code=404, detail="pipeline run not found")
    progress = None
    if run.status not in {"PENDING"}:
        progress = stage_progress(db, run)
    return PipelineStatusLite(
        batch_id=batch_id,
        status=run.status,
        current_stage=run.current_stage,
        progress=progress,
        pipeline_run_id=run.id,
    )


@router.get("/batch/{batch_id}", response_model=PipelineRunOut)
def read_pipeline_for_batch(batch_id: str, db: Session = Depends(get_db)) -> PipelineRunOut:
    run = latest_pipeline_run(db, batch_id)
    if run is None:
        raise HTTPException(status_code=404, detail="pipeline run not found")
    return to_out(db, run)


@router.get("/{pipeline_run_id}", response_model=PipelineRunOut)
def read_pipeline_run(pipeline_run_id: int, db: Session = Depends(get_db)) -> PipelineRunOut:
    run = get_pipeline_run(db, pipeline_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="pipeline run not found")
    return to_out(db, run)
