from __future__ import annotations

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    AiExplanation,
    Batch,
    ClusterProfile,
    DatasetProfile,
    DistrictProfile,
    EnumeratorProfile,
    MlEvidence,
    PipelineRun,
    RuleViolation,
    StatisticalEvidence,
    UnifiedRiskAssessment,
    ValidationRun,
)
from app.modules.dashboard.schemas import (
    AnomalyRow,
    EvidenceItem,
    GroupRow,
    PipelineStage,
    SourceCard,
)
from app.modules.validation.explanation.repository import display_status, get_explanation, to_block
from app.modules.validation.fusion.classification import (
    CONFIRMED_STATUSES,
    anomaly_status_of,
    classify_assessment,
    hydrate_assessment_rule_codes,
    is_confirmed_anomaly,
    should_auto_explain,
)
from app.modules.validation.intelligence.repository import list_detections
from app.modules.pipeline.repository import (
    active_pipeline_run,
    latest_pipeline_run,
    list_stages,
)

_SEVERITY_ORDER = case(
    (UnifiedRiskAssessment.severity == "CRITICAL", 0),
    (UnifiedRiskAssessment.severity == "HIGH", 1),
    (UnifiedRiskAssessment.severity == "MEDIUM", 2),
    (UnifiedRiskAssessment.severity == "LOW", 3),
    else_=4,
)


def latest_batch(db: Session) -> Batch | None:
    return db.scalars(select(Batch).order_by(Batch.created_at.desc())).first()


def get_batch(db: Session, batch_id: str | None) -> Batch | None:
    if batch_id:
        return db.scalars(select(Batch).where(Batch.batch_id == batch_id)).first()
    latest = latest_batch(db)
    if latest is None:
        return None
    pipe = latest_pipeline_run(db, latest.batch_id)
    if pipe is not None and pipe.status in {"PENDING", "RUNNING"}:
        stable = db.scalars(
            select(PipelineRun)
            .where(
                PipelineRun.is_active.is_(True),
                PipelineRun.status.in_(["COMPLETED", "PARTIAL"]),
            )
            .order_by(PipelineRun.id.desc())
        ).first()
        if stable is not None:
            found = db.scalars(select(Batch).where(Batch.batch_id == stable.batch_id)).first()
            if found is not None:
                return found
    return latest


def latest_run(db: Session, batch_id: str, validation_type: str) -> ValidationRun | None:
    return db.scalars(
        select(ValidationRun)
        .where(
            ValidationRun.batch_id == batch_id,
            ValidationRun.validation_type == validation_type,
        )
        .order_by(ValidationRun.id.desc())
    ).first()


def _pipeline_engine_run(db: Session, run: PipelineRun, stage: str) -> ValidationRun | None:
    for row in list_stages(db, run.id):
        if row.stage == stage and row.engine_run_id:
            found = db.get(ValidationRun, row.engine_run_id)
            if found is not None:
                return found
    return None


def dashboard_fusion_run(db: Session, batch_id: str) -> ValidationRun | None:
    latest = latest_pipeline_run(db, batch_id)
    active = active_pipeline_run(db, batch_id)
    if latest is not None and latest.status in {"PENDING", "RUNNING"}:
        if active is not None and active.status in {"COMPLETED", "PARTIAL"}:
            return _pipeline_engine_run(db, active, "FUSION")
        return None
    if active is not None and active.status in {"COMPLETED", "PARTIAL"}:
        fusion = _pipeline_engine_run(db, active, "FUSION")
        if fusion is not None:
            return fusion
    return latest_run(db, batch_id, "fusion")


def _run_stage(
    run: ValidationRun | None,
    *,
    label: str,
    stage_id: str,
    unavailable_if_missing: bool = False,
) -> PipelineStage:
    if run is None:
        status = "UNAVAILABLE" if unavailable_if_missing else "PENDING"
        return PipelineStage(id=stage_id, label=label, status=status)
    mapped = {
        "COMPLETED": "COMPLETED",
        "FAILED": "FAILED",
        "RUNNING": "PROCESSING",
        "PROCESSING": "PROCESSING",
        "INSUFFICIENT": "UNAVAILABLE",
        "insufficient": "UNAVAILABLE",
    }.get(run.status, "PROCESSING" if run.completed_at is None else "COMPLETED")
    if run.status == "COMPLETED":
        mapped = "COMPLETED"
    elif run.status in {"FAILED", "PROFILE_FAILED"}:
        mapped = "FAILED"
    elif run.status in {"insufficient", "INSUFFICIENT", "SKIPPED"}:
        mapped = "UNAVAILABLE"
    else:
        mapped = "PROCESSING"
    return PipelineStage(
        id=stage_id,
        label=label,
        status=mapped,  # type: ignore[arg-type]
        timestamp=run.completed_at or run.started_at,
        record_count=run.records_checked,
        detail=run.status,
    )


def pipeline_for_batch(db: Session, batch: Batch) -> list[PipelineStage]:
    from app.modules.pipeline.repository import latest_pipeline_run, list_stages

    latest = latest_pipeline_run(db, batch.batch_id)
    if latest is not None:
        mapped = []
        for row in list_stages(db, latest.id):
            mapped.append(
                PipelineStage(
                    id=row.stage.lower(),
                    label=row.stage.replace("_", " "),
                    status=row.status if row.status in {"PENDING", "PROCESSING", "COMPLETED", "FAILED", "UNAVAILABLE"} else "PENDING",  # type: ignore[arg-type]
                    timestamp=row.completed_at or row.started_at,
                    record_count=row.records_processed,
                    detail=row.error or (row.detail_json or {}).get("status"),
                )
            )
        return mapped
    source_status = "COMPLETED" if batch.source else "PENDING"
    ingest_map = {
        "RECEIVED": "PROCESSING",
        "PROCESSING": "PROCESSING",
        "COMPLETED": "COMPLETED",
        "PROFILED": "COMPLETED",
        "PROFILING": "COMPLETED",
        "FAILED": "FAILED",
        "PROFILE_FAILED": "COMPLETED",
    }
    ingest_status = ingest_map.get(batch.status, "PENDING")
    parquet_status = "COMPLETED" if batch.parquet_path else ("FAILED" if batch.status == "FAILED" else "PENDING")
    dataset = db.scalars(select(DatasetProfile).where(DatasetProfile.batch_id == batch.batch_id)).first()
    if batch.status == "PROFILING":
        sirl_status = "PROCESSING"
    elif batch.status == "PROFILE_FAILED":
        sirl_status = "FAILED"
    elif dataset is not None or batch.status == "PROFILED":
        sirl_status = "COMPLETED"
    else:
        sirl_status = "PENDING"
    fusion = latest_run(db, batch.batch_id, "fusion")
    explanations = db.scalars(
        select(func.count()).select_from(AiExplanation).where(AiExplanation.batch_id == batch.batch_id)
    ).one()
    expl_available = db.scalars(
        select(func.count())
        .select_from(AiExplanation)
        .where(AiExplanation.batch_id == batch.batch_id, AiExplanation.status == "available")
    ).one()
    if explanations == 0:
        expl_status = "PENDING" if fusion and fusion.status == "COMPLETED" else "PENDING"
        if fusion is None:
            expl_status = "PENDING"
    elif expl_available:
        expl_status = "COMPLETED"
    else:
        expl_status = "UNAVAILABLE"
    stages = [
        PipelineStage(
            id="source",
            label="eSIGMA / CSV",
            status=source_status,  # type: ignore[arg-type]
            detail=batch.source,
            timestamp=batch.created_at,
        ),
        PipelineStage(
            id="ingestion",
            label="INGESTION",
            status=ingest_status,  # type: ignore[arg-type]
            timestamp=batch.completed_at or batch.created_at,
            record_count=batch.records,
            detail=batch.status,
        ),
        PipelineStage(
            id="standardization",
            label="STANDARDIZATION",
            status="COMPLETED" if batch.schema_version else ingest_status,  # type: ignore[arg-type]
            timestamp=batch.completed_at,
            detail=batch.schema_version,
        ),
        PipelineStage(
            id="parquet",
            label="PARQUET",
            status=parquet_status,  # type: ignore[arg-type]
            timestamp=batch.completed_at,
            detail=batch.parquet_path,
        ),
        PipelineStage(
            id="sirl",
            label="SIRL",
            status=sirl_status,  # type: ignore[arg-type]
            timestamp=dataset.profiled_at if dataset else None,
            record_count=dataset.record_count if dataset else None,
        ),
        _run_stage(latest_run(db, batch.batch_id, "rules"), label="RULES", stage_id="rules"),
        _run_stage(latest_run(db, batch.batch_id, "statistics"), label="STATISTICS", stage_id="statistics"),
        _run_stage(
            latest_run(db, batch.batch_id, "ml"),
            label="ML",
            stage_id="ml",
            unavailable_if_missing=True,
        ),
        _run_stage(fusion, label="FUSION", stage_id="fusion"),
        PipelineStage(
            id="explanation",
            label="AI EXPLANATION",
            status=expl_status,  # type: ignore[arg-type]
            record_count=int(expl_available or 0),
            detail=f"{int(expl_available or 0)} available / {int(explanations or 0)} stored",
        ),
    ]
    return stages


def _to_row(row: UnifiedRiskAssessment, explanation: AiExplanation | None) -> AnomalyRow:
    classified = classify_assessment(row)
    refs = row.evidence_refs_json or {}
    detectors = list(refs.get("detectors") or [])
    return AnomalyRow(
        batch_id=row.batch_id,
        record_id=row.record_id,
        risk_score=row.risk_score,
        severity=row.severity,
        agreement=row.agreement,
        evidence_confidence=row.confidence,
        enumerator_id=row.enumerator_id,
        cluster_id=row.cluster_id,
        district_id=row.district_id,
        available_sources=list(row.available_sources_json or []),
        missing_sources=list(row.missing_sources_json or []),
        source_scores=dict(row.source_scores_json or {}),
        source_severities=dict(row.source_severities_json or {}),
        escalation_applied=bool(row.escalation_applied),
        anomaly_status=classified["anomaly_status"],
        classification_reason=classified["classification_reason"],
        anomaly_reason=classified["classification_reason"],
        intelligence_classification=row.intelligence_classification,
        primary_detector=row.primary_detector,
        detector_count=row.detector_count,
        review_required=bool(row.review_required),
        detectors=detectors,
        ai_explanation_status=display_status(explanation, detected=should_auto_explain(row)),
        ai_explanation_reason=explanation.reason if explanation else None,
    )


def overview(db: Session, batch_id: str | None, allowed_districts: list[str] | None = None) -> dict:
    batch = get_batch(db, batch_id)
    if batch is None:
        return {
            "available": False,
            "message": "No batches available. Ingest a CSV or eSIGMA extract to begin.",
        }
    fusion = dashboard_fusion_run(db, batch.batch_id)
    latest_pipe = latest_pipeline_run(db, batch.batch_id)
    processing = latest_pipe is not None and latest_pipe.status in {"PENDING", "RUNNING"}
    if fusion is None or fusion.status != "COMPLETED":
        return {
            "available": False,
            "batch_id": batch.batch_id,
            "survey_code": batch.survey_code,
            "total_records": batch.records,
            "processed": None,
            "fusion_status": None if fusion is None else fusion.status,
            "pipeline_status": None if latest_pipe is None else latest_pipe.status,
            "current_stage": None if latest_pipe is None else latest_pipe.current_stage,
            "message": (
                "Survey analysis is running."
                if processing
                else "Fusion assessment is not available for this batch."
            ),
        }
    rows = db.scalars(
        select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.validation_run_id == fusion.id)
    ).all()
    hydrate_assessment_rule_codes(db, rows)
    if allowed_districts is not None:
        rows = [row for row in rows if (row.district_id or "") in allowed_districts]
    confirmed = [row for row in rows if is_confirmed_anomaly(row)]
    review = [row for row in rows if anomaly_status_of(row) == "REVIEW"]
    critical = sum(1 for row in confirmed if str(row.severity or "").upper() == "CRITICAL")
    high = sum(1 for row in confirmed if str(row.severity or "").upper() == "HIGH")
    medium = len(review)
    total = int(batch.records or 0) or len(rows)
    clean = max(0, total - len(confirmed) - len(review))
    processed = total
    flagged = len(confirmed)
    detections = list_detections(db, batch.batch_id)
    signals: dict[str, int] = {}
    for item in detections:
        signals[item.detector_type] = signals.get(item.detector_type, 0) + 1
    enumerators = {row.enumerator_id for row in rows if row.enumerator_id}
    active = active_pipeline_run(db, batch.batch_id)
    return {
        "available": True,
        "batch_id": batch.batch_id,
        "survey_code": batch.survey_code,
        "total_records": batch.records,
        "processed": processed,
        "high_risk": high,
        "medium_risk": medium,
        "low_risk": 0,
        "clean": clean,
        "critical": critical,
        "confirmed_anomalies": flagged,
        "review_signals": len(review),
        "anomaly_rate": (flagged / processed) if processed else 0.0,
        "enumerators": len(enumerators),
        "fusion_run_id": fusion.id,
        "fusion_status": fusion.status,
        "validation_errors": sum(1 for row in rows if (row.intelligence_classification or "") == "VALIDATION_ERROR"),
        "unusual_patterns": sum(1 for row in rows if (row.intelligence_classification or "") == "UNUSUAL_PATTERN"),
        "investigation_required": sum(1 for row in rows if (row.intelligence_classification or "") == "INVESTIGATION_REQUIRED"),
        "enumerator_alerts": sum(1 for item in detections if item.entity_type == "enumerator"),
        "cluster_alerts": sum(1 for item in detections if item.entity_type == "cluster"),
        "temporal_alerts": sum(1 for item in detections if item.detector_type == "TEMPORAL_CHANGE"),
        "geographic_alerts": sum(1 for item in detections if item.detector_type == "GEOGRAPHIC_CLUSTER"),
        "relationship_alerts": sum(
            1 for item in detections if (item.category or "") == "RELATIONSHIP" or str(item.detector_type or "").startswith("REL_")
        ),
        "quality_signals": signals,
        "pipeline_status": None if latest_pipe is None else latest_pipe.status,
        "current_stage": None if latest_pipe is None else latest_pipe.current_stage,
        "active_pipeline_run_id": None if active is None else active.id,
        "message": None,
    }


def list_anomalies(
    db: Session,
    *,
    batch_id: str | None,
    page: int,
    page_size: int,
    severity: str | None,
    min_risk_score: float | None,
    agreement: str | None,
    enumerator_id: str | None,
    cluster_id: str | None,
    district_id: str | None,
    evidence_source: str | None,
    ai_status: str | None,
    q: str | None,
    allowed_districts: list[str] | None = None,
    classification_scope: str | None = "confirmed",
    detector_type: str | None = None,
    classification: str | None = None,
    baseline_type: str | None = None,
) -> dict:
    batch = get_batch(db, batch_id)
    if batch is None:
        return {"available": False, "total": 0, "page": page, "page_size": page_size, "items": [], "message": "No batches available."}
    fusion = dashboard_fusion_run(db, batch.batch_id)
    if fusion is None:
        return {
            "available": False,
            "batch_id": batch.batch_id,
            "total": 0,
            "page": page,
            "page_size": page_size,
            "items": [],
            "message": "Fusion assessment is not available for this batch.",
        }
    query = select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.validation_run_id == fusion.id)
    if severity:
        query = query.where(UnifiedRiskAssessment.severity == severity)
    if min_risk_score is not None:
        query = query.where(UnifiedRiskAssessment.risk_score >= min_risk_score)
    if agreement:
        query = query.where(UnifiedRiskAssessment.agreement == agreement)
    if enumerator_id:
        query = query.where(UnifiedRiskAssessment.enumerator_id == enumerator_id)
    if cluster_id:
        query = query.where(UnifiedRiskAssessment.cluster_id == cluster_id)
    if district_id:
        query = query.where(UnifiedRiskAssessment.district_id == district_id)
    if allowed_districts is not None:
        query = query.where(UnifiedRiskAssessment.district_id.in_(allowed_districts))
    if q:
        like = f"%{q}%"
        query = query.where(
            or_(
                UnifiedRiskAssessment.record_id.ilike(like),
                UnifiedRiskAssessment.enumerator_id.ilike(like),
                UnifiedRiskAssessment.cluster_id.ilike(like),
                UnifiedRiskAssessment.district_id.ilike(like),
            )
        )
    rows = list(db.scalars(query.order_by(_SEVERITY_ORDER, UnifiedRiskAssessment.risk_score.desc())).all())
    hydrate_assessment_rule_codes(db, rows)
    explanations = {
        row.record_id: row
        for row in db.scalars(select(AiExplanation).where(AiExplanation.batch_id == batch.batch_id)).all()
    }
    scope = (classification_scope or "confirmed").lower()
    if scope == "confirmed":
        rows = [row for row in rows if is_confirmed_anomaly(row)]
    elif scope == "review":
        rows = [row for row in rows if anomaly_status_of(row) == "REVIEW"]
    elif scope == "review_and_confirmed":
        rows = [row for row in rows if anomaly_status_of(row) in {"REVIEW", *CONFIRMED_STATUSES}]
    elif scope == "all":
        pass
    if detector_type:
        rows = [row for row in rows if detector_type in list((row.evidence_refs_json or {}).get("detectors") or [])]
    if classification:
        rows = [row for row in rows if (row.intelligence_classification or "") == classification]
    if baseline_type:
        rows = [
            row
            for row in rows
            if any(
                (item or {}).get("baseline_type") == baseline_type
                for item in (row.evidence_refs_json or {}).get("quality_detections") or []
            )
        ]
    if evidence_source:
        rows = [row for row in rows if evidence_source in (row.available_sources_json or [])]
    if ai_status:
        filtered = []
        for row in rows:
            status = display_status(explanations.get(row.record_id), detected=should_auto_explain(row))
            if status == ai_status:
                filtered.append(row)
        rows = filtered
    total = len(rows)
    start = max(0, (page - 1) * page_size)
    page_rows = rows[start : start + page_size]
    items = [_to_row(row, explanations.get(row.record_id)) for row in page_rows]
    return {
        "available": True,
        "batch_id": batch.batch_id,
        "fusion_run_id": fusion.id,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
        "message": None,
    }


def record_detail(
    db: Session,
    batch_id: str,
    record_id: str,
    allowed_districts: list[str] | None = None,
) -> dict:
    batch = get_batch(db, batch_id)
    if batch is None:
        return {"available": False, "batch_id": batch_id, "record_id": record_id, "message": "batch not found"}
    fusion = dashboard_fusion_run(db, batch.batch_id)
    if fusion is None:
        return {
            "available": False,
            "batch_id": batch.batch_id,
            "record_id": record_id,
            "message": "Fusion assessment is not available.",
        }
    row = db.scalars(
        select(UnifiedRiskAssessment).where(
            UnifiedRiskAssessment.validation_run_id == fusion.id,
            UnifiedRiskAssessment.record_id == record_id,
        )
    ).first()
    if row is None:
        return {
            "available": False,
            "batch_id": batch.batch_id,
            "record_id": record_id,
            "message": "Record assessment not found.",
        }
    if allowed_districts is not None and (row.district_id or "") not in allowed_districts:
        return {
            "available": False,
            "batch_id": batch.batch_id,
            "record_id": record_id,
            "message": "Record is outside assigned scope.",
        }
    hydrate_assessment_rule_codes(db, [row])
    refs = row.evidence_refs_json or {}
    rules = []
    rule_ids = list(refs.get("rule_violation_ids") or [])
    if rule_ids:
        rules = list(db.scalars(select(RuleViolation).where(RuleViolation.id.in_(rule_ids))).all())
        rules = [item for item in rules if item.record_id == record_id]
    stats = []
    stat_ids = list(refs.get("statistical_evidence_ids") or [])
    if stat_ids:
        stats = list(db.scalars(select(StatisticalEvidence).where(StatisticalEvidence.id.in_(stat_ids))).all())
        stats = [item for item in stats if item.record_id == record_id]
    ml_rows = []
    ml_ids = list(refs.get("ml_evidence_ids") or [])
    if ml_ids:
        ml_rows = list(db.scalars(select(MlEvidence).where(MlEvidence.id.in_(ml_ids))).all())
        ml_rows = [item for item in ml_rows if item.record_id == record_id]
    scores = dict(row.source_scores_json or {})
    severities = dict(row.source_severities_json or {})
    missing = set(row.missing_sources_json or [])
    available = set(row.available_sources_json or [])

    def status_for(name: str) -> str:
        if name in missing:
            return "UNAVAILABLE"
        if name in available:
            return "AVAILABLE"
        return "UNAVAILABLE"

    sources = [
        SourceCard(
            source="rules",
            status=status_for("rules"),
            score=scores.get("rules"),
            severity=severities.get("rules"),
            detections=len(rules),
            items=[
                EvidenceItem(
                    source="rules",
                    code=item.rule_code,
                    field=item.field,
                    observed_value=item.observed_value,
                    expected=item.expected_condition,
                    severity=item.severity,
                    message=item.message,
                )
                for item in rules
            ],
        ),
        SourceCard(
            source="statistics",
            status=status_for("statistics"),
            score=scores.get("statistics"),
            severity=severities.get("statistics"),
            detections=len(stats),
            items=[
                EvidenceItem(
                    source="statistics",
                    detector=item.detector,
                    variable=item.variable,
                    observed_value=item.observed_value,
                    score=item.score,
                    threshold=item.threshold,
                    severity=item.severity,
                )
                for item in stats
            ],
        ),
        SourceCard(
            source="ml",
            status=status_for("ml"),
            score=scores.get("ml"),
            severity=severities.get("ml"),
            detections=len(ml_rows),
            items=[
                EvidenceItem(
                    source="ml",
                    detector=item.model_type,
                    model_type=item.model_type,
                    anomaly_score=item.anomaly_score,
                    score=item.anomaly_score,
                    severity=item.severity,
                    message=item.prediction,
                )
                for item in ml_rows
            ],
        ),
    ]
    intel_items = [
        item
        for item in list_detections(db, batch.batch_id)
        if item.record_id == record_id
        or (item.enumerator_id and item.enumerator_id == row.enumerator_id)
        or (item.cluster_id and item.cluster_id == row.cluster_id)
    ]
    sources.append(
        SourceCard(
            source="intelligence",
            status="AVAILABLE" if intel_items else "UNAVAILABLE",
            detections=len(intel_items),
            items=[
                EvidenceItem(
                    source="intelligence",
                    detector=item.detector_type,
                    field=item.field_name,
                    observed_value=item.observed_value,
                    expected=None if item.expected_value is None else str(item.expected_value),
                    severity=item.severity,
                    message=item.explanation,
                )
                for item in intel_items
            ],
        )
    )
    explanation_row = get_explanation(db, batch.batch_id, record_id)
    explanation = to_block(explanation_row).model_dump() if explanation_row else None
    dataset = db.scalars(select(DatasetProfile).where(DatasetProfile.batch_id == batch.batch_id)).first()
    return {
        "available": True,
        "batch_id": batch.batch_id,
        "record_id": record_id,
        "assessment": _to_row(row, explanation_row),
        "sources": sources,
        "explanation": explanation,
        "sirl_available": dataset is not None,
        "escalation_applied": bool(row.escalation_applied),
        "escalation_reason": row.escalation_reason,
        "message": None,
    }


def _group_missing(profile_json: dict | None) -> float | None:
    if not profile_json:
        return None
    value = profile_json.get("missingness_rate")
    if value is None:
        value = profile_json.get("missing_rate")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def group_rows(
    db: Session,
    batch_id: str | None,
    grain: str,
    *,
    view: str = "current_batch",
) -> list[GroupRow]:
    from app.modules.dashboard.scope import assessments_for_view, fused_batch_ids, is_cumulative

    assessments = assessments_for_view(db, batch_id, view)
    buckets: dict[str, list[UnifiedRiskAssessment]] = {}
    for row in assessments:
        key = {
            "enumerator": row.enumerator_id,
            "cluster": row.cluster_id,
            "district": row.district_id,
        }.get(grain)
        if not key:
            continue
        buckets.setdefault(key, []).append(row)
    missing_map: dict[str, float | None] = {}
    extra_district: dict[str, str | None] = {}
    extra_cluster: dict[str, str | None] = {}
    profile_filter = True
    if is_cumulative(view):
        processed = fused_batch_ids(db)
        if grain == "enumerator":
            profile_filter = EnumeratorProfile.batch_id.in_(processed)
        elif grain == "cluster":
            profile_filter = ClusterProfile.batch_id.in_(processed)
        elif grain == "district":
            profile_filter = DistrictProfile.batch_id.in_(processed)
    elif batch_id:
        if grain == "enumerator":
            profile_filter = EnumeratorProfile.batch_id == batch_id
        elif grain == "cluster":
            profile_filter = ClusterProfile.batch_id == batch_id
        elif grain == "district":
            profile_filter = DistrictProfile.batch_id == batch_id
    missing_weight: dict[str, list[tuple[float, int]]] = {}
    if grain == "enumerator":
        query = select(EnumeratorProfile)
        if profile_filter is not True:
            query = query.where(profile_filter)
        for profile in db.scalars(query).all():
            rate = _group_missing(profile.profile_json)
            extra_district.setdefault(profile.enumerator_id, (profile.profile_json or {}).get("related_id"))
            if rate is not None:
                missing_weight.setdefault(profile.enumerator_id, []).append((rate, int(profile.record_count or 0)))
    elif grain == "cluster":
        query = select(ClusterProfile)
        if profile_filter is not True:
            query = query.where(profile_filter)
        for profile in db.scalars(query).all():
            rate = _group_missing(profile.profile_json)
            extra_district.setdefault(profile.cluster_id, profile.district_id)
            if rate is not None:
                missing_weight.setdefault(profile.cluster_id, []).append((rate, int(profile.record_count or 0)))
    elif grain == "district":
        query = select(DistrictProfile)
        if profile_filter is not True:
            query = query.where(profile_filter)
        for profile in db.scalars(query).all():
            rate = _group_missing(profile.profile_json)
            if rate is not None:
                missing_weight.setdefault(profile.district_id, []).append((rate, int(profile.record_count or 0)))
    for key, parts in missing_weight.items():
        weight = sum(count for _rate, count in parts)
        if weight:
            missing_map[key] = sum(rate * count for rate, count in parts) / weight
        elif parts:
            missing_map[key] = sum(rate for rate, _count in parts) / len(parts)
    items = []
    for key, rows in sorted(buckets.items()):
        high = sum(1 for row in rows if is_confirmed_anomaly(row) and str(row.severity or "").upper() == "HIGH")
        medium = sum(1 for row in rows if anomaly_status_of(row) == "REVIEW")
        low = sum(1 for row in rows if anomaly_status_of(row) == "NORMAL")
        critical = sum(1 for row in rows if is_confirmed_anomaly(row) and str(row.severity or "").upper() == "CRITICAL")
        n = len(rows)
        enumerators = {row.enumerator_id for row in rows if row.enumerator_id}
        confirmed = high + critical
        clusters = {row.cluster_id for row in rows if row.cluster_id}
        items.append(
            GroupRow(
                id=key,
                district_id=extra_district.get(key) or (rows[0].district_id if grain != "district" else key),
                cluster_id=next(iter(clusters)) if grain == "enumerator" and len(clusters) == 1 else extra_cluster.get(key),
                records=n,
                high_risk=high,
                medium_risk=medium,
                low_risk=low,
                critical=critical,
                anomaly_rate=confirmed / n if n else 0.0,
                missingness_rate=missing_map.get(key),
                enumerators=len(enumerators) if grain != "enumerator" else None,
            )
        )
    items.sort(key=lambda item: (-(item.high_risk + item.critical), -item.records))
    return items


def group_detail(db: Session, batch_id: str, grain: str, group_id: str) -> dict:
    items = group_rows(db, batch_id, grain)
    match = next((item for item in items if item.id == group_id), None)
    fusion = latest_run(db, batch_id, "fusion")
    high_records = []
    sources: list[str] = []
    if fusion is not None:
        column = {
            "enumerator": UnifiedRiskAssessment.enumerator_id,
            "cluster": UnifiedRiskAssessment.cluster_id,
            "district": UnifiedRiskAssessment.district_id,
        }[grain]
        rows = db.scalars(
            select(UnifiedRiskAssessment).where(
                UnifiedRiskAssessment.validation_run_id == fusion.id,
                column == group_id,
            )
        ).all()
        hydrate_assessment_rule_codes(db, rows)
        rows = [row for row in rows if is_confirmed_anomaly(row)]
        explanations = {
            row.record_id: row
            for row in db.scalars(select(AiExplanation).where(AiExplanation.batch_id == batch_id)).all()
        }
        high_records = [_to_row(row, explanations.get(row.record_id)) for row in rows]
        counts: dict[str, int] = {}
        for row in rows:
            for source in row.available_sources_json or []:
                counts[source] = counts.get(source, 0) + 1
        sources = [name for name, _ in sorted(counts.items(), key=lambda item: -item[1])]
    return {
        "available": match is not None,
        "batch_id": batch_id,
        "grain": grain,
        "group_id": group_id,
        "items": [match] if match else [],
        "high_risk_records": high_records,
        "common_sources": sources,
        "message": None if match else "Group not found in fused assessments.",
    }


def report_rows(
    db: Session,
    batch_id: str | None,
    kind: str,
    *,
    allowed_districts: list[str] | None = None,
    view: str = "current_batch",
) -> tuple[list[str], list[list[str]], dict[str, str]]:
    from datetime import UTC, datetime

    from app.models import Investigation
    from app.modules.dashboard.scope import (
        CUMULATIVE_LABEL,
        VIEW_CUMULATIVE,
        assessments_for_view,
        fused_batch_count,
        is_cumulative,
    )

    generated = datetime.now(UTC).isoformat()
    methodology = settings.fusion_methodology_version
    cumulative = is_cumulative(view)
    meta = {
        "batch_id": "ALL" if cumulative else str(batch_id or ""),
        "view": VIEW_CUMULATIVE if cumulative else "current_batch",
        "report_type": kind,
        "generated_at": generated,
        "methodology_version": methodology,
        "data_classification": "SYNTHETIC_DEMO",
    }
    if cumulative:
        meta["scope_label"] = CUMULATIVE_LABEL
        meta["batch_count"] = str(fused_batch_count(db))
    assessments = assessments_for_view(db, batch_id, view)
    if allowed_districts is not None:
        assessments = [row for row in assessments if (row.district_id or "") in allowed_districts]
    if not assessments and kind != "investigations":
        return ["message"], [["Fusion assessment is not available."]], meta
    explanation_query = select(AiExplanation)
    if not cumulative and batch_id:
        explanation_query = explanation_query.where(AiExplanation.batch_id == batch_id)
    explanations = {
        (row.batch_id, row.record_id): row for row in db.scalars(explanation_query).all()
    }
    extra = ["report_type", "generated_at", "methodology_version"]
    extra_vals = [kind, generated, methodology]
    if kind == "high-risk":
        assessments = [row for row in assessments if is_confirmed_anomaly(row)]
    if kind == "anomalies":
        assessments = [row for row in assessments if is_confirmed_anomaly(row)]
    if kind in {"high-risk", "anomalies", "batch"}:
        header = [
            "batch_id",
            "record_id",
            "risk_score",
            "severity",
            "anomaly_status",
            "evidence_confidence",
            "agreement",
            "enumerator_id",
            "cluster_id",
            "district_id",
            "available_sources",
            "ai_explanation_status",
            *extra,
        ]
        lines = [
            [
                row.batch_id,
                row.record_id,
                str(row.risk_score),
                row.severity,
                classify_assessment(row)["anomaly_status"],
                str(row.confidence),
                row.agreement,
                row.enumerator_id or "",
                row.cluster_id or "",
                row.district_id or "",
                "|".join(row.available_sources_json or []),
                display_status(explanations.get((row.batch_id, row.record_id)), detected=should_auto_explain(row)),
                *extra_vals,
            ]
            for row in assessments
        ]
        return header, lines, meta
    if kind == "enumerators":
        header = ["enumerator_id", "district_id", "records", "high_risk", "medium_risk", "anomaly_rate", "missingness_rate", *extra]
        lines = [
            [
                item.id,
                item.district_id or "",
                str(item.records),
                str(item.high_risk),
                str(item.medium_risk),
                "" if item.anomaly_rate is None else str(item.anomaly_rate),
                "" if item.missingness_rate is None else str(item.missingness_rate),
                *extra_vals,
            ]
            for item in group_rows(db, batch_id, "enumerator", view=view)
        ]
        return header, lines, meta
    if kind == "districts":
        header = ["district_id", "records", "high_risk", "anomaly_rate", "enumerators", *extra]
        lines = [
            [
                item.id,
                str(item.records),
                str(item.high_risk),
                "" if item.anomaly_rate is None else str(item.anomaly_rate),
                str(item.enumerators or 0),
                *extra_vals,
            ]
            for item in group_rows(db, batch_id, "district", view=view)
        ]
        return header, lines, meta
    if kind == "investigations":
        query = select(Investigation)
        if not cumulative and batch_id:
            query = query.where(Investigation.batch_id == batch_id)
        if allowed_districts is not None:
            query = query.where(Investigation.district_id.in_(allowed_districts))
        cases = list(db.scalars(query.order_by(Investigation.id.asc())).all())
        by_record = {(row.batch_id, row.record_id): row for row in assessments}
        header = [
            "batch_id",
            "record_id",
            "risk_score",
            "severity",
            "investigation_status",
            "assigned_supervisor",
            "action",
            "notes",
            "priority",
            "created_at",
            "updated_at",
            "resolved_at",
            *extra,
        ]
        lines = [
            [
                item.batch_id,
                item.record_id,
                "" if by_record.get((item.batch_id, item.record_id)) is None else str(by_record[(item.batch_id, item.record_id)].risk_score),
                "" if by_record.get((item.batch_id, item.record_id)) is None else by_record[(item.batch_id, item.record_id)].severity,
                item.status,
                item.assigned_to or "",
                item.action or "",
                (item.supervisor_notes or "").replace("\n", " "),
                item.priority,
                item.created_at.isoformat() if item.created_at else "",
                item.updated_at.isoformat() if item.updated_at else "",
                item.resolved_at.isoformat() if item.resolved_at else "",
                *extra_vals,
            ]
            for item in cases
        ]
        return header, lines, meta
    return ["message"], [["Unknown report kind."]], meta


def esigma_status(*, probe: bool = False) -> dict:
    mock = bool(settings.esigma_mock_mode)
    live_configured = bool(settings.esigma_base_url and settings.esigma_api_key)
    configured = mock or live_configured
    if mock:
        status = "MOCK"
        notice = (
            "eSIGMA mock mode is enabled. Live credentials stay on the backend and are never sent to the browser."
        )
    elif not live_configured:
        status = "NOT_CONFIGURED"
        notice = "eSIGMA is not configured."
    else:
        status = "CONFIGURED_BUT_UNVERIFIED"
        notice = (
            "Live eSIGMA credentials are present. The official request contract has not been verified "
            "in this process; use probe=true for a safe GET against ESIGMA_BASE_URL."
        )
        if probe:
            from app.modules.ingestion.esigma_client import LiveESigmaClient
            from app.modules.ingestion.errors import IngestError

            client = LiveESigmaClient(
                base_url=settings.esigma_base_url,
                api_key=settings.esigma_api_key,
                timeout_seconds=min(float(settings.esigma_timeout_seconds), 5.0),
            )
            try:
                client.fetch()
                status = "REACHABLE"
                notice = "Live eSIGMA endpoint responded."
            except IngestError as exc:
                if exc.status_code == 401:
                    status = "AUTH_FAILED"
                    notice = "eSIGMA authentication failed."
                elif exc.status_code == 504:
                    status = "TIMEOUT"
                    notice = "eSIGMA request timed out."
                else:
                    status = "UNAVAILABLE"
                    notice = "eSIGMA is unavailable."
            except Exception:
                status = "UNAVAILABLE"
                notice = "eSIGMA is unavailable."
    return {"mock_mode": mock, "configured": configured, "status": status, "notice": notice}
