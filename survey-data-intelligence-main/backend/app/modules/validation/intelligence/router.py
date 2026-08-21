from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import DetectorConfig, QualityDetection, User, ValidationRun
from app.modules.auth.deps import get_current_user, require_admin
from app.modules.dashboard.service import get_batch
from app.modules.validation.errors import ValidationError
from app.modules.validation.intelligence.analytics import (
    anomaly_summary,
    cluster_analytics,
    detector_analytics,
    distribution_analytics,
    district_analytics,
    enumerator_analytics,
    explorer,
    temporal_series,
)
from app.modules.validation.intelligence.orchestrator import run_intelligence
from app.modules.validation.intelligence.registry import enabled_map
from app.modules.validation.intelligence.schemas import (
    AnomalySummaryOut,
    DetectorConfigOut,
    DetectorConfigUpdate,
    IntelligenceRunResponse,
    QualityDetectionOut,
)

router = APIRouter(tags=["intelligence"])


def _to_detection(row: QualityDetection) -> QualityDetectionOut:
    return QualityDetectionOut(
        id=row.id,
        batch_id=row.batch_id,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        record_id=row.record_id,
        enumerator_id=row.enumerator_id,
        cluster_id=row.cluster_id,
        district_id=row.district_id,
        household_id=row.household_id,
        detector_type=row.detector_type,
        category=row.category,
        classification=row.classification,
        severity=row.severity,
        confidence=row.confidence,
        review_required=row.review_required,
        field_name=row.field_name,
        observed_value=row.observed_value,
        expected_value=row.expected_value,
        deviation=row.deviation,
        baseline_type=row.baseline_type,
        explanation=row.explanation,
        evidence_json=row.evidence_json or {},
    )


@router.post("/validation/intelligence/run/{batch_id}", response_model=IntelligenceRunResponse)
def run_intelligence_endpoint(batch_id: str, db: Session = Depends(get_db)) -> IntelligenceRunResponse:
    try:
        return run_intelligence(db, batch_id)
    except ValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/detectors", response_model=list[DetectorConfigOut])
def list_detectors(db: Session = Depends(get_db)) -> list[DetectorConfigOut]:
    enabled_map(db)
    rows = db.scalars(select(DetectorConfig).order_by(DetectorConfig.category, DetectorConfig.detector_id)).all()
    return [
        DetectorConfigOut(
            id=row.id,
            detector_id=row.detector_id,
            name=row.name,
            category=row.category,
            description=row.description,
            enabled=row.enabled,
            severity=row.severity,
            thresholds_json=row.thresholds_json,
        )
        for row in rows
    ]


@router.patch("/detectors/{detector_id}", response_model=DetectorConfigOut)
def update_detector(
    detector_id: str,
    payload: DetectorConfigUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> DetectorConfigOut:
    row = db.scalars(select(DetectorConfig).where(DetectorConfig.detector_id == detector_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="detector not found")
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.severity is not None:
        row.severity = payload.severity
    if payload.thresholds_json is not None:
        row.thresholds_json = payload.thresholds_json
    db.commit()
    db.refresh(row)
    return DetectorConfigOut(
        id=row.id,
        detector_id=row.detector_id,
        name=row.name,
        category=row.category,
        description=row.description,
        enabled=row.enabled,
        severity=row.severity,
        thresholds_json=row.thresholds_json,
    )


@router.get("/anomalies/summary", response_model=AnomalySummaryOut)
def read_anomaly_summary(
    batch_id: str | None = None,
    view: str | None = Query(None),
    db: Session = Depends(get_db),
) -> AnomalySummaryOut:
    return anomaly_summary(db, batch_id, view)


@router.get("/anomalies")
def list_quality_anomalies(
    batch_id: str | None = None,
    detector_type: str | None = None,
    classification: str | None = None,
    baseline_type: str | None = None,
    entity_type: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    batch = get_batch(db, batch_id)
    if batch is None:
        return {"available": False, "items": []}
    run = db.scalars(
        select(ValidationRun)
        .where(ValidationRun.batch_id == batch.batch_id, ValidationRun.validation_type == "intelligence")
        .order_by(ValidationRun.id.desc())
    ).first()
    if run is None:
        return {"available": False, "items": [], "message": "Intelligence run is not available."}
    query = select(QualityDetection).where(QualityDetection.validation_run_id == run.id)
    if detector_type:
        query = query.where(QualityDetection.detector_type == detector_type)
    if classification:
        query = query.where(QualityDetection.classification == classification)
    if baseline_type:
        query = query.where(QualityDetection.baseline_type == baseline_type)
    if entity_type:
        query = query.where(QualityDetection.entity_type == entity_type)
    rows = db.scalars(query).all()
    return {"available": True, "batch_id": batch.batch_id, "items": [_to_detection(row) for row in rows]}


@router.get("/analytics/temporal")
def analytics_temporal(
    batch_id: str | None = None,
    view: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    return temporal_series(db, batch_id, view)


@router.get("/analytics/enumerators/{enumerator_id}")
def analytics_enumerator(enumerator_id: str, batch_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    return enumerator_analytics(db, enumerator_id, batch_id)


@router.get("/analytics/clusters/{cluster_id}")
def analytics_cluster(cluster_id: str, batch_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    return cluster_analytics(db, cluster_id, batch_id)


@router.get("/analytics/districts/{district_id}")
def analytics_district(district_id: str, batch_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    return district_analytics(db, district_id, batch_id)


@router.get("/analytics/detectors")
def analytics_detectors(
    batch_id: str | None = None,
    view: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    return detector_analytics(db, batch_id, view)


@router.get("/analytics/distributions")
def analytics_distributions(batch_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    return distribution_analytics(db, batch_id)


@router.get("/analytics/explorer")
def analytics_explorer(
    batch_id: str | None = None,
    variable: str = "employment_rate",
    level: str = "district",
    view: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    return explorer(db, batch_id, variable, level, view)
