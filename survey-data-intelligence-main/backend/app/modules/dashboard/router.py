from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.modules.auth.deps import district_scope, get_current_user
from app.modules.dashboard.schemas import (
    AnomalyListResponse,
    ESigmaStatusResponse,
    GroupDetailResponse,
    GroupListResponse,
    OverviewResponse,
    PipelineResponse,
    RecordDetailResponse,
)
from app.modules.dashboard.scope import (
    CUMULATIVE_LABEL,
    NO_CUMULATIVE_MESSAGE,
    VIEW_CUMULATIVE,
    fused_batch_count,
    is_cumulative,
    normalize_view,
)
from app.modules.dashboard.service import (
    esigma_status,
    get_batch,
    group_detail,
    group_rows,
    list_anomalies,
    overview,
    pipeline_for_batch,
    record_detail,
    report_rows,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
esigma_router = APIRouter(prefix="/esigma", tags=["esigma"])


@esigma_router.get("/status", response_model=ESigmaStatusResponse)
def read_esigma_status(probe: bool = False) -> ESigmaStatusResponse:
    return ESigmaStatusResponse(**esigma_status(probe=probe))


@router.get("/overview", response_model=OverviewResponse)
def read_overview(
    batch_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OverviewResponse:
    return OverviewResponse(**overview(db, batch_id, allowed_districts=district_scope(user)))


@router.get("/pipeline/{batch_id}", response_model=PipelineResponse)
def read_pipeline(batch_id: str, db: Session = Depends(get_db)) -> PipelineResponse:
    batch = get_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    return PipelineResponse(batch_id=batch.batch_id, source=batch.source, stages=pipeline_for_batch(db, batch))


@router.get("/anomalies", response_model=AnomalyListResponse)
def read_anomalies(
    batch_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    severity: str | None = None,
    min_risk_score: float | None = None,
    agreement: str | None = None,
    enumerator_id: str | None = None,
    cluster_id: str | None = None,
    district_id: str | None = None,
    evidence_source: str | None = None,
    ai_status: str | None = None,
    q: str | None = None,
    classification_scope: str | None = Query("confirmed"),
    detector_type: str | None = None,
    classification: str | None = None,
    baseline_type: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnomalyListResponse:
    payload = list_anomalies(
        db,
        batch_id=batch_id,
        page=page,
        page_size=page_size,
        severity=severity,
        min_risk_score=min_risk_score,
        agreement=agreement,
        enumerator_id=enumerator_id,
        cluster_id=cluster_id,
        district_id=district_id,
        evidence_source=evidence_source,
        ai_status=ai_status,
        q=q,
        classification_scope=classification_scope,
        detector_type=detector_type,
        classification=classification,
        baseline_type=baseline_type,
        allowed_districts=district_scope(user),
    )
    return AnomalyListResponse(**payload)


@router.get("/anomalies/summary")
def read_dashboard_anomaly_summary(
    batch_id: str | None = None,
    view: str | None = Query(None),
    db: Session = Depends(get_db),
):
    from app.modules.validation.intelligence.analytics import anomaly_summary

    return anomaly_summary(db, batch_id, view)


@router.get("/records/{batch_id}/{record_id}", response_model=RecordDetailResponse)
def read_record(
    batch_id: str,
    record_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecordDetailResponse:
    payload = record_detail(db, batch_id, record_id, allowed_districts=district_scope(user))
    return RecordDetailResponse(**payload)


def _group_list_response(db: Session, batch_id: str | None, grain: str, view: str | None) -> GroupListResponse:
    selected = normalize_view(view)
    if is_cumulative(selected):
        count = fused_batch_count(db)
        if count == 0:
            return GroupListResponse(
                available=False,
                grain=grain,
                view=selected,
                message=NO_CUMULATIVE_MESSAGE,
            )
        items = group_rows(db, None, grain, view=selected)
        return GroupListResponse(
            available=True,
            batch_id=None,
            grain=grain,
            items=items,
            view=selected,
            batch_count=count,
            message=CUMULATIVE_LABEL,
        )
    batch = get_batch(db, batch_id)
    if batch is None:
        return GroupListResponse(available=False, grain=grain, message="No batches available.")
    items = group_rows(db, batch.batch_id, grain, view=selected)
    return GroupListResponse(available=True, batch_id=batch.batch_id, grain=grain, items=items, view=selected)


@router.get("/enumerators", response_model=GroupListResponse)
def read_enumerators(
    batch_id: str | None = None,
    view: str | None = Query(None),
    db: Session = Depends(get_db),
) -> GroupListResponse:
    return _group_list_response(db, batch_id, "enumerator", view)


@router.get("/enumerators/{enumerator_id}", response_model=GroupDetailResponse)
def read_enumerator(enumerator_id: str, batch_id: str | None = None, db: Session = Depends(get_db)) -> GroupDetailResponse:
    batch = get_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    return GroupDetailResponse(**group_detail(db, batch.batch_id, "enumerator", enumerator_id))


@router.get("/clusters", response_model=GroupListResponse)
def read_clusters(
    batch_id: str | None = None,
    view: str | None = Query(None),
    db: Session = Depends(get_db),
) -> GroupListResponse:
    return _group_list_response(db, batch_id, "cluster", view)


@router.get("/districts", response_model=GroupListResponse)
def read_districts(
    batch_id: str | None = None,
    view: str | None = Query(None),
    db: Session = Depends(get_db),
) -> GroupListResponse:
    return _group_list_response(db, batch_id, "district", view)


@router.get("/reports/{kind}")
def download_report(
    kind: str,
    batch_id: str | None = None,
    view: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    allowed = {"high-risk", "anomalies", "enumerators", "districts", "batch", "investigations"}
    if kind not in allowed:
        raise HTTPException(status_code=404, detail="report not found")
    selected = normalize_view(view)
    if is_cumulative(selected):
        if fused_batch_count(db) == 0:
            raise HTTPException(status_code=404, detail=NO_CUMULATIVE_MESSAGE)
        header, rows, meta = report_rows(
            db, None, kind, allowed_districts=district_scope(user), view=selected
        )
        filename = f"{kind}-cumulative.csv"
    else:
        batch = get_batch(db, batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="batch not found")
        header, rows, meta = report_rows(
            db, batch.batch_id, kind, allowed_districts=district_scope(user), view=selected
        )
        filename = f"{kind}-{batch.batch_id}.csv"
    buffer = io.StringIO()
    for key, value in meta.items():
        buffer.write(f"# {key}={value}\n")
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    payload = buffer.getvalue()
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
