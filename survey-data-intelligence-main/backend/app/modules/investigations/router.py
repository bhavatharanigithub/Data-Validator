from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.modules.auth.deps import get_current_user
from app.modules.investigations.presenters import audit_out, with_assessment
from app.modules.investigations.schemas import (
    AuditOut,
    InvestigationCreate,
    InvestigationListOut,
    InvestigationOut,
    InvestigationPatch,
    NoteCreate,
)
from app.modules.investigations.service import (
    add_note,
    create_investigation,
    get_investigation,
    list_audit,
    list_investigations,
    patch_investigation,
)
from app.modules.validation.errors import ValidationError

router = APIRouter(prefix="/investigations", tags=["investigations"])


def _raise(exc: ValidationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("", response_model=InvestigationOut)
def create_case(
    body: InvestigationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InvestigationOut:
    try:
        row = create_investigation(db, body, user)
    except ValidationError as exc:
        _raise(exc)
        raise
    return with_assessment(db, row)


@router.get("", response_model=InvestigationListOut)
def list_cases(
    status: str | None = None,
    priority: str | None = None,
    enumerator: str | None = None,
    district: str | None = None,
    assigned_to: str | None = None,
    batch_id: str | None = None,
    record_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InvestigationListOut:
    rows, kpis = list_investigations(
        db,
        user,
        status=status,
        priority=priority,
        enumerator=enumerator,
        district=district,
        assigned_to=assigned_to,
        batch_id=batch_id,
        record_id=record_id,
    )
    return InvestigationListOut(items=[with_assessment(db, row) for row in rows], kpis=kpis)


@router.get("/{investigation_id}", response_model=InvestigationOut)
def read_case(
    investigation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InvestigationOut:
    try:
        row = get_investigation(db, investigation_id, user)
    except ValidationError as exc:
        _raise(exc)
        raise
    return with_assessment(db, row)


@router.patch("/{investigation_id}", response_model=InvestigationOut)
def update_case(
    investigation_id: int,
    body: InvestigationPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InvestigationOut:
    try:
        row = patch_investigation(db, investigation_id, body, user)
    except ValidationError as exc:
        _raise(exc)
        raise
    return with_assessment(db, row)


@router.post("/{investigation_id}/notes", response_model=InvestigationOut)
def create_note(
    investigation_id: int,
    body: NoteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InvestigationOut:
    try:
        row = add_note(db, investigation_id, body, user)
    except ValidationError as exc:
        _raise(exc)
        raise
    return with_assessment(db, row)


@router.get("/{investigation_id}/audit", response_model=list[AuditOut])
def read_audit(
    investigation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AuditOut]:
    try:
        rows = list_audit(db, investigation_id, user)
    except ValidationError as exc:
        _raise(exc)
        raise
    return [audit_out(row) for row in rows]
