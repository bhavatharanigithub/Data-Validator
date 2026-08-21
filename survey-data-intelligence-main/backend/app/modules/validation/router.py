from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, ValidationRun
from app.modules.auth.deps import require_admin
from app.modules.validation.errors import ValidationError
from app.modules.validation.rules.engine import _summary, list_violations, run_rules
from app.modules.validation.rules.repository import (
    create_rule,
    delete_rule,
    get_rule_out,
    list_rules,
    set_enabled,
    update_rule,
)
from app.modules.validation.rules.schemas import (
    RuleCreate,
    RuleOut,
    RuleUpdate,
    ValidationRunDetail,
    ValidationRunResponse,
)

router = APIRouter(prefix="/validation", tags=["validation"])


def _raise(exc: ValidationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/rules", response_model=RuleOut)
def create_validation_rule(
    payload: RuleCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> RuleOut:
    try:
        return create_rule(db, payload)
    except ValidationError as exc:
        _raise(exc)
        raise


@router.get("/rules", response_model=list[RuleOut])
def list_validation_rules(
    enabled_only: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[RuleOut]:
    return list_rules(db, enabled=enabled_only)


@router.post("/rules/run/{batch_id}", response_model=ValidationRunResponse)
def run_rule_validation(batch_id: str, db: Session = Depends(get_db)) -> ValidationRunResponse:
    try:
        return run_rules(db, batch_id)
    except ValidationError as exc:
        _raise(exc)
        raise


@router.get("/rules/{rule_id}", response_model=RuleOut)
def get_validation_rule(rule_id: int, db: Session = Depends(get_db)) -> RuleOut:
    try:
        return get_rule_out(db, rule_id)
    except ValidationError as exc:
        _raise(exc)
        raise


@router.put("/rules/{rule_id}", response_model=RuleOut)
def update_validation_rule(
    rule_id: int, payload: RuleUpdate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> RuleOut:
    try:
        return update_rule(db, rule_id, payload)
    except ValidationError as exc:
        _raise(exc)
        raise


@router.delete("/rules/{rule_id}")
def delete_validation_rule(
    rule_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict:
    try:
        delete_rule(db, rule_id)
    except ValidationError as exc:
        _raise(exc)
        raise
    return {"success": True}


@router.patch("/rules/{rule_id}/enable", response_model=RuleOut)
def enable_rule(
    rule_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> RuleOut:
    try:
        return set_enabled(db, rule_id, True)
    except ValidationError as exc:
        _raise(exc)
        raise


@router.patch("/rules/{rule_id}/disable", response_model=RuleOut)
def disable_rule(
    rule_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> RuleOut:
    try:
        return set_enabled(db, rule_id, False)
    except ValidationError as exc:
        _raise(exc)
        raise


@router.get("/runs/{run_id}", response_model=ValidationRunDetail)
def get_run(run_id: int, db: Session = Depends(get_db)) -> ValidationRunDetail:
    run = db.get(ValidationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="validation run not found")
    items = list_violations(db, run_id)
    summary = _summary(run, [{"severity": item.severity} for item in items])
    return ValidationRunDetail(**summary.model_dump(), items=items)
