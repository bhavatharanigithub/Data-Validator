from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ValidationRun
from app.modules.validation.errors import ValidationError
from app.modules.validation.statistics.engine import _summary, run_statistics
from app.modules.validation.statistics.repository import list_evidence
from app.modules.validation.statistics.schemas import StatisticsRunDetail, StatisticsRunResponse

router = APIRouter(prefix="/validation", tags=["validation-statistics"])


def _raise(exc: ValidationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/statistics/run/{batch_id}", response_model=StatisticsRunResponse)
def run_statistical_validation(batch_id: str, db: Session = Depends(get_db)) -> StatisticsRunResponse:
    try:
        return run_statistics(db, batch_id)
    except ValidationError as exc:
        _raise(exc)
        raise


@router.get("/statistics/runs/{run_id}", response_model=StatisticsRunDetail)
def get_statistical_run(run_id: int, db: Session = Depends(get_db)) -> StatisticsRunDetail:
    run = db.get(ValidationRun, run_id)
    if run is None or run.validation_type != "statistics":
        raise HTTPException(status_code=404, detail="statistical validation run not found")
    items = list_evidence(db, run_id)
    summary = _summary(
        run,
        [{"severity": item.severity} for item in items],
        historical_available=False,
    )
    return StatisticsRunDetail(**summary.model_dump(), items=items)
