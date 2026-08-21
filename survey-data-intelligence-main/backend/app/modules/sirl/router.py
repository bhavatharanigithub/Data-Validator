from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.modules.sirl.enrichment import enrich_profile
from app.modules.sirl.errors import SirlError
from app.modules.sirl.schemas import AiEnrichment, ProfileRunResponse, SirlContext
from app.modules.sirl.service import get_context, profile_batch

router = APIRouter(prefix="/sirl", tags=["sirl"])


def _raise(exc: SirlError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/profile/{batch_id}", response_model=ProfileRunResponse)
def run_profile(batch_id: str, db: Session = Depends(get_db)) -> ProfileRunResponse:
    try:
        return profile_batch(db, batch_id)
    except SirlError as exc:
        _raise(exc)
        raise


@router.get("/profile/{batch_id}", response_model=SirlContext)
def read_profile(batch_id: str, db: Session = Depends(get_db)) -> SirlContext:
    try:
        return get_context(db, batch_id)
    except SirlError as exc:
        _raise(exc)
        raise


@router.get("/profile/{batch_id}/variables")
def read_variables(batch_id: str, db: Session = Depends(get_db)) -> dict:
    context = read_profile(batch_id, db)
    return {"batch_id": batch_id, "variables": context.variable_context}


@router.get("/profile/{batch_id}/enumerators")
def read_enumerators(batch_id: str, db: Session = Depends(get_db)) -> dict:
    context = read_profile(batch_id, db)
    return {"batch_id": batch_id, "enumerators": context.enumerator_context}


@router.get("/profile/{batch_id}/clusters")
def read_clusters(batch_id: str, db: Session = Depends(get_db)) -> dict:
    context = read_profile(batch_id, db)
    return {"batch_id": batch_id, "clusters": context.cluster_context}


@router.get("/profile/{batch_id}/districts")
def read_districts(batch_id: str, db: Session = Depends(get_db)) -> dict:
    context = read_profile(batch_id, db)
    return {"batch_id": batch_id, "districts": context.district_context}


@router.post("/enrich/{batch_id}", response_model=AiEnrichment)
def run_enrichment(batch_id: str, db: Session = Depends(get_db)) -> AiEnrichment:
    try:
        return enrich_profile(db, batch_id)
    except SirlError as exc:
        _raise(exc)
        raise
