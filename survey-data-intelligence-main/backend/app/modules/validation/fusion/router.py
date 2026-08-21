from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ValidationRun
from app.modules.validation.errors import ValidationError
from app.modules.validation.fusion.engine import _summary, run_fusion
from app.modules.validation.fusion.repository import get_dataset_assessment, list_assessments
from app.modules.validation.fusion.schemas import FusionRunDetail, FusionRunResponse

router = APIRouter(prefix="/validation", tags=["validation-fusion"])


def _raise(exc: ValidationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/fusion/run/{batch_id}", response_model=FusionRunResponse)
def run_fusion_validation(batch_id: str, db: Session = Depends(get_db)) -> FusionRunResponse:
    try:
        return run_fusion(db, batch_id)
    except ValidationError as exc:
        _raise(exc)
        raise


@router.get("/fusion/runs/{run_id}", response_model=FusionRunDetail)
def get_fusion_run(run_id: int, db: Session = Depends(get_db)) -> FusionRunDetail:
    run = db.get(ValidationRun, run_id)
    if run is None or run.validation_type != "fusion":
        raise HTTPException(status_code=404, detail="fusion validation run not found")
    items = list_assessments(db, run_id)
    summary = _summary(run, [item.model_dump() for item in items])
    dataset = get_dataset_assessment(db, run_id, run.batch_id)
    payload = summary.model_dump()
    payload["has_dataset_assessment"] = dataset is not None
    return FusionRunDetail(
        **payload,
        items=items,
        dataset_assessment=dataset,
    )
