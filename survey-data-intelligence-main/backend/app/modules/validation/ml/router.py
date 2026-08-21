from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ValidationRun
from app.modules.validation.errors import ValidationError
from app.modules.validation.ml.engine import _summary, run_ml
from app.modules.validation.ml.repository import list_ml_evidence
from app.modules.validation.ml.schemas import MlRunDetail, MlRunResponse

router = APIRouter(prefix="/validation", tags=["validation-ml"])


def _raise(exc: ValidationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/ml/run/{batch_id}", response_model=MlRunResponse)
def run_ml_validation(batch_id: str, db: Session = Depends(get_db)) -> MlRunResponse:
    try:
        return run_ml(db, batch_id)
    except ValidationError as exc:
        _raise(exc)
        raise


@router.get("/ml/runs/{run_id}", response_model=MlRunDetail)
def get_ml_run(run_id: int, db: Session = Depends(get_db)) -> MlRunDetail:
    run = db.get(ValidationRun, run_id)
    if run is None or run.validation_type != "ml":
        raise HTTPException(status_code=404, detail="ml validation run not found")
    items = list_ml_evidence(db, run_id)
    summary = _summary(run, [item.model_dump() for item in items])
    return MlRunDetail(**summary.model_dump(), items=items)
