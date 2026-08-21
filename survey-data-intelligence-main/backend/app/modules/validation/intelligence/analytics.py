from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ClusterProfile,
    DetectorConfig,
    DistrictProfile,
    EnumeratorProfile,
    ValidationRun,
)
from app.modules.dashboard.service import get_batch
from app.modules.validation.intelligence.repository import list_detections
from app.modules.validation.intelligence.schemas import AnomalySummaryOut


def anomaly_summary(db: Session, batch_id: str | None, view: str | None = None) -> AnomalySummaryOut:
    from app.modules.dashboard.scope import assessments_for_view, detections_for_view, is_cumulative, latest_run_ids
    from app.modules.dashboard.service import get_batch

    rows = assessments_for_view(db, batch_id, view)
    detections = detections_for_view(db, batch_id, view)
    meta: dict = {}
    if is_cumulative(view):
        run_ids = latest_run_ids(db, "intelligence")
        if run_ids:
            intel_run = db.get(ValidationRun, max(run_ids))
            meta = intel_run.skipped_rules_json if intel_run and isinstance(intel_run.skipped_rules_json, dict) else {}
    else:
        batch = get_batch(db, batch_id)
        if batch is None:
            return AnomalySummaryOut()
        intel_run = db.scalars(
            select(ValidationRun)
            .where(ValidationRun.batch_id == batch.batch_id, ValidationRun.validation_type == "intelligence")
            .order_by(ValidationRun.id.desc())
        ).first()
        meta = intel_run.skipped_rules_json if intel_run and isinstance(intel_run.skipped_rules_json, dict) else {}
    classes = Counter(
        (row.intelligence_classification or "INFORMATIONAL") for row in rows
    )
    by_detector = Counter(item.detector_type for item in detections)
    return AnomalySummaryOut(
        total=len(detections),
        high=sum(1 for item in detections if item.severity == "HIGH"),
        medium=sum(1 for item in detections if item.severity == "MEDIUM"),
        low=sum(1 for item in detections if item.severity in {"LOW", "NONE"}),
        validation_errors=classes.get("VALIDATION_ERROR", 0),
        unusual_patterns=classes.get("UNUSUAL_PATTERN", 0) + sum(1 for item in detections if item.classification == "UNUSUAL_PATTERN"),
        investigation_required=classes.get("INVESTIGATION_REQUIRED", 0),
        informational=classes.get("INFORMATIONAL", 0),
        by_detector=dict(by_detector),
        by_entity=dict(Counter(item.entity_type for item in detections)),
        detectors_available=list(meta.get("available") or []),
        detectors_skipped=list(meta.get("skipped") or []),
        skip_reasons=dict(meta.get("reason") or {}),
    )


def temporal_series(db: Session, batch_id: str | None, view: str | None = None) -> dict:
    from app.modules.dashboard.scope import CUMULATIVE_LABEL, detections_for_view, fused_batch_count, is_cumulative
    from app.modules.dashboard.service import get_batch

    if is_cumulative(view):
        if fused_batch_count(db) == 0:
            return {"available": False, "items": [], "message": "No processed batches available for cumulative analysis."}
        detections = [item for item in detections_for_view(db, None, view) if item.detector_type == "TEMPORAL_CHANGE"]
        items = [
            {
                "period": item.entity_id,
                "observed": item.observed_value,
                "baseline": item.expected_value,
                "threshold": (item.expected_value or 0) + 0.08,
                "deviation": item.deviation,
                "batch_id": item.batch_id,
            }
            for item in detections
        ]
        return {
            "available": bool(items),
            "batch_id": None,
            "view": "cumulative",
            "message": None if items else "Not available for cumulative view",
            "items": items,
            "scope_label": CUMULATIVE_LABEL,
        }
    batch = get_batch(db, batch_id)
    if batch is None:
        return {"available": False, "items": [], "message": "No batches available."}
    detections = [item for item in list_detections(db, batch.batch_id) if item.detector_type == "TEMPORAL_CHANGE"]
    items = [
        {
            "period": item.entity_id,
            "observed": item.observed_value,
            "baseline": item.expected_value,
            "threshold": (item.expected_value or 0) + 0.08,
            "deviation": item.deviation,
        }
        for item in detections
    ]
    skipped = anomaly_summary(db, batch.batch_id)
    available = "TEMPORAL" in skipped.detectors_available
    return {
        "available": available or bool(items),
        "batch_id": batch.batch_id,
        "items": items,
        "message": None if available or items else skipped.skip_reasons.get("TEMPORAL"),
    }


def enumerator_analytics(db: Session, enumerator_id: str, batch_id: str | None) -> dict:
    batch = get_batch(db, batch_id)
    if batch is None:
        return {"available": False, "message": "No batches available."}
    profile = db.scalars(
        select(EnumeratorProfile).where(
            EnumeratorProfile.batch_id == batch.batch_id,
            EnumeratorProfile.enumerator_id == enumerator_id,
        )
    ).first()
    detections = [
        item
        for item in list_detections(db, batch.batch_id)
        if item.enumerator_id == enumerator_id or (item.entity_type == "enumerator" and item.entity_id == enumerator_id)
    ]
    others = db.scalars(
        select(EnumeratorProfile).where(EnumeratorProfile.batch_id == batch.batch_id)
    ).all()
    comparison = []
    for row in others:
        means = (row.profile_json or {}).get("numeric_means") or {}
        comparison.append(
            {
                "enumerator_id": row.enumerator_id,
                "employment_rate": (row.profile_json or {}).get("employment_rate"),
                "mean_income": means.get("income"),
                "record_count": row.record_count,
                "highlight": row.enumerator_id == enumerator_id,
            }
        )
    return {
        "available": True,
        "batch_id": batch.batch_id,
        "enumerator_id": enumerator_id,
        "profile": None if profile is None else profile.profile_json,
        "detections": [
            {"detector_type": item.detector_type, "explanation": item.explanation, "observed": item.observed_value, "baseline": item.expected_value}
            for item in detections
        ],
        "comparison": comparison,
    }


def cluster_analytics(db: Session, cluster_id: str, batch_id: str | None) -> dict:
    batch = get_batch(db, batch_id)
    if batch is None:
        return {"available": False, "message": "No batches available."}
    profile = db.scalars(
        select(ClusterProfile).where(
            ClusterProfile.batch_id == batch.batch_id,
            ClusterProfile.cluster_id == cluster_id,
        )
    ).first()
    detections = [
        item
        for item in list_detections(db, batch.batch_id)
        if item.cluster_id == cluster_id or (item.entity_type == "cluster" and item.entity_id == cluster_id)
    ]
    return {
        "available": True,
        "batch_id": batch.batch_id,
        "cluster_id": cluster_id,
        "profile": None if profile is None else profile.profile_json,
        "detections": [
            {"detector_type": item.detector_type, "explanation": item.explanation, "observed": item.observed_value, "baseline": item.expected_value}
            for item in detections
        ],
    }


def district_analytics(db: Session, district_id: str, batch_id: str | None) -> dict:
    batch = get_batch(db, batch_id)
    if batch is None:
        return {"available": False, "message": "No batches available."}
    profile = db.scalars(
        select(DistrictProfile).where(
            DistrictProfile.batch_id == batch.batch_id,
            DistrictProfile.district_id == district_id,
        )
    ).first()
    detections = [
        item
        for item in list_detections(db, batch.batch_id)
        if item.district_id == district_id or (item.entity_type == "district" and item.entity_id == district_id)
    ]
    return {
        "available": True,
        "batch_id": batch.batch_id,
        "district_id": district_id,
        "profile": None if profile is None else profile.profile_json,
        "detections": [
            {"detector_type": item.detector_type, "explanation": item.explanation, "observed": item.observed_value, "baseline": item.expected_value}
            for item in detections
        ],
    }


def detector_analytics(db: Session, batch_id: str | None, view: str | None = None) -> dict:
    from app.modules.dashboard.scope import CUMULATIVE_LABEL, assessments_for_view, fused_batch_count, is_cumulative
    from app.modules.validation.fusion.classification import is_confirmed_anomaly, anomaly_status_of

    summary = anomaly_summary(db, batch_id, view)
    configs = list(db.scalars(select(DetectorConfig).order_by(DetectorConfig.category, DetectorConfig.detector_id)).all())
    rows = assessments_for_view(db, batch_id, view)
    confirmed = sum(1 for row in rows if is_confirmed_anomaly(row))
    review = sum(1 for row in rows if anomaly_status_of(row) == "REVIEW")
    payload = {
        "available": True,
        "summary": summary.model_dump(),
        "items": [{"detector": key, "count": value} for key, value in summary.by_detector.items()],
        "records_processed": len(rows),
        "confirmed_anomalies": confirmed,
        "review_signals": review,
        "risk_distribution": dict(Counter((row.severity or "UNKNOWN").upper() for row in rows)),
        "classification_distribution": dict(Counter(anomaly_status_of(row) for row in rows)),
        "view": "cumulative" if is_cumulative(view) else "current_batch",
        "configs": [
            {
                "detector_id": row.detector_id,
                "name": row.name,
                "category": row.category,
                "enabled": row.enabled,
                "severity": row.severity,
                "description": row.description,
                "thresholds_json": row.thresholds_json,
            }
            for row in configs
        ],
    }
    if is_cumulative(view):
        payload["batch_id"] = None
        payload["batch_count"] = fused_batch_count(db)
        payload["scope_label"] = CUMULATIVE_LABEL
        if fused_batch_count(db) == 0:
            payload["available"] = False
            payload["message"] = "No processed batches available for cumulative analysis."
    return payload


def distribution_analytics(db: Session, batch_id: str | None) -> dict:
    batch = get_batch(db, batch_id)
    if batch is None:
        return {"available": False, "items": []}
    detections = [item for item in list_detections(db, batch.batch_id) if item.detector_type == "DISTRIBUTION_SHIFT"]
    return {
        "available": True,
        "batch_id": batch.batch_id,
        "items": [
            {
                "field": item.field_name,
                "distance": item.observed_value,
                "threshold": item.expected_value,
                "explanation": item.explanation,
            }
            for item in detections
        ],
    }


def explorer(db: Session, batch_id: str | None, variable: str, level: str, view: str | None = None) -> dict:
    from app.modules.dashboard.scope import CUMULATIVE_LABEL, fused_batch_count, fused_batch_ids, is_cumulative
    from app.modules.dashboard.service import get_batch

    model = {
        "district": DistrictProfile,
        "cluster": ClusterProfile,
        "enumerator": EnumeratorProfile,
    }.get(level or "district", DistrictProfile)
    if is_cumulative(view):
        if fused_batch_count(db) == 0:
            return {
                "available": False,
                "items": [],
                "message": "No processed batches available for cumulative analysis.",
                "view": "cumulative",
            }
        processed = fused_batch_ids(db)
        rows = list(db.scalars(select(model).where(model.batch_id.in_(processed))).all())
        grouped: dict[str, dict] = {}
        for row in rows:
            payload = row.profile_json or {}
            if level == "district":
                entity_id = row.district_id
            elif level == "cluster":
                entity_id = row.cluster_id
            else:
                entity_id = row.enumerator_id
            if not entity_id:
                continue
            current = grouped.setdefault(
                str(entity_id),
                {"id": entity_id, "record_count": 0, "employment_weight": 0.0, "employment_total": 0.0, "value_weight": 0.0, "value_total": 0.0},
            )
            count = int(row.record_count or 0)
            current["record_count"] += count
            emp = payload.get("employment_rate")
            if emp is not None and count:
                current["employment_total"] += float(emp) * count
                current["employment_weight"] += count
            means = payload.get("numeric_means") or {}
            raw = payload.get(variable) if variable in payload else means.get(variable)
            if raw is not None and count:
                current["value_total"] += float(raw) * count
                current["value_weight"] += count
        items = []
        for current in grouped.values():
            items.append(
                {
                    "id": current["id"],
                    "record_count": current["record_count"],
                    "value": (current["value_total"] / current["value_weight"]) if current["value_weight"] else None,
                    "employment_rate": (current["employment_total"] / current["employment_weight"])
                    if current["employment_weight"]
                    else None,
                }
            )
        values = [item["value"] for item in items if item["value"] is not None]
        return {
            "available": True,
            "batch_id": None,
            "view": "cumulative",
            "variable": variable,
            "level": level,
            "national": sum(values) / len(values) if values else None,
            "items": items,
            "scope_label": CUMULATIVE_LABEL,
            "batch_count": fused_batch_count(db),
        }
    batch = get_batch(db, batch_id)
    if batch is None:
        return {"available": False, "items": []}
    model = {
        "district": DistrictProfile,
        "cluster": ClusterProfile,
        "enumerator": EnumeratorProfile,
    }.get(level or "district", DistrictProfile)
    rows = list(db.scalars(select(model).where(model.batch_id == batch.batch_id)).all())
    items = []
    for row in rows:
        payload = row.profile_json or {}
        means = payload.get("numeric_means") or {}
        entity_id = getattr(row, f"{level}_id", None) if level != "enumerator" else row.enumerator_id
        if level == "district":
            entity_id = row.district_id
        elif level == "cluster":
            entity_id = row.cluster_id
        items.append(
            {
                "id": entity_id,
                "record_count": row.record_count,
                "value": payload.get(variable) if variable in payload else means.get(variable),
                "employment_rate": payload.get("employment_rate"),
            }
        )
    values = [item["value"] for item in items if item["value"] is not None]
    national = sum(values) / len(values) if values else None
    return {
        "available": True,
        "batch_id": batch.batch_id,
        "variable": variable,
        "level": level,
        "national": national,
        "items": items,
    }
