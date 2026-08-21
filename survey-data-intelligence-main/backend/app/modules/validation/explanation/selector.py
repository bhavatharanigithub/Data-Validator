from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    MlEvidence,
    RuleViolation,
    StatisticalEvidence,
    UnifiedRiskAssessment,
    ValidationRule,
)
from app.modules.sirl.repositories import load_context
from app.modules.validation.fusion.classification import classify_assessment


def _size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, default=str, sort_keys=True).encode("utf-8"))


def context_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, default=str, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _compact_rule(row: RuleViolation, rule: ValidationRule | None) -> dict[str, Any]:
    return {
        "id": row.id,
        "rule_code": row.rule_code,
        "rule_description": (rule.description or rule.name) if rule is not None else row.message,
        "severity": row.severity,
        "field": row.field,
        "operator": rule.operator if rule is not None else None,
        "observed_value": row.observed_value,
        "expected_condition": row.expected_condition,
        "message": row.message,
    }


def _compact_stat(row: StatisticalEvidence) -> dict[str, Any]:
    extra = row.evidence_json or {}
    historical = extra.get("historical") or extra.get("historical_context")
    return {
        "id": row.id,
        "variable": row.variable,
        "detector": row.detector,
        "scope": row.scope,
        "observed_value": row.observed_value,
        "baseline_mean": row.baseline_value,
        "baseline_value": row.baseline_value,
        "baseline_std": row.baseline_std,
        "score": row.score,
        "z_score": extra.get("z_score", row.score if row.detector == "z_score" else None),
        "threshold": row.threshold,
        "severity": row.severity,
        "enumerator_id": row.enumerator_id,
        "cluster_id": row.cluster_id,
        "district_id": row.district_id,
        "group_id": extra.get("group_id"),
        "baseline_iqr": extra.get("iqr") or extra.get("baseline_iqr"),
        "historical_context": historical if historical is not None else "unavailable",
    }


def _compact_ml(row: MlEvidence) -> dict[str, Any]:
    extra = row.evidence_json or {}
    feature_values = extra.get("feature_values")
    return {
        "id": row.id,
        "model_type": row.model_type,
        "model_version": row.model_version,
        "anomaly_score": row.anomaly_score,
        "raw_model_score": row.raw_model_score,
        "severity": row.severity,
        "feature_names": list(row.feature_names_json or []),
        "feature_values": feature_values if feature_values is not None else "unavailable",
        "training_source": row.training_source,
        "training_records": row.training_records,
        "prediction": row.prediction,
    }


def _load_by_ids(db: Session, model, ids: list[int], record_id: str):
    if not ids:
        return []
    rows = db.scalars(select(model).where(model.id.in_(ids))).all()
    return [row for row in rows if row.record_id == record_id]


def _sirl_slice(
    db: Session,
    batch_id: str,
    assessment: UnifiedRiskAssessment,
    variables: list[str],
) -> dict[str, Any]:
    context = load_context(db, batch_id)
    if context is None:
        return {"available": False}
    dataset = context.dataset_context or {}
    payload: dict[str, Any] = {
        "available": True,
        "record_count": dataset.get("record_count"),
        "numeric_measures": dataset.get("numeric_measures") or [],
        "historical_context_available": bool(
            (context.historical_context or {}).get("historical_context_available")
        ),
    }
    variables_out = []
    for name in variables[:8]:
        item = (context.variable_context or {}).get(name)
        if not isinstance(item, dict):
            continue
        compact = {
            "name": name,
            "kind": item.get("kind"),
            "mean": item.get("mean"),
            "standard_deviation": item.get("standard_deviation"),
            "missing_rate": item.get("missing_rate"),
        }
        variables_out.append(compact)
    payload["variables"] = variables_out
    if assessment.enumerator_id:
        group = (context.enumerator_context or {}).get(assessment.enumerator_id)
        if isinstance(group, dict):
            payload["enumerator"] = {
                "id": assessment.enumerator_id,
                "record_count": group.get("record_count"),
                "numeric_means": group.get("numeric_means") or {},
            }
    if assessment.cluster_id:
        group = (context.cluster_context or {}).get(assessment.cluster_id)
        if isinstance(group, dict):
            payload["cluster"] = {
                "id": assessment.cluster_id,
                "record_count": group.get("record_count"),
                "numeric_means": group.get("numeric_means") or {},
            }
    if assessment.district_id:
        group = (context.district_context or {}).get(assessment.district_id)
        if isinstance(group, dict):
            payload["district"] = {
                "id": assessment.district_id,
                "record_count": group.get("record_count"),
                "numeric_means": group.get("numeric_means") or {},
            }
    return payload


def has_detected_evidence(assessment: UnifiedRiskAssessment | None) -> bool:
    if assessment is None:
        return False
    refs = assessment.evidence_refs_json or {}
    for key in ("rule_violation_ids", "statistical_evidence_ids", "ml_evidence_ids"):
        if refs.get(key):
            return True
    return False


def has_usable_evidence(payload: dict[str, Any]) -> bool:
    if payload.get("rule_evidence") or payload.get("statistical_evidence") or payload.get("ml_evidence"):
        return True
    assessment = payload.get("unified_assessment") or {}
    return bool(assessment.get("available_sources"))


def select_explanation_context(
    db: Session,
    assessment: UnifiedRiskAssessment,
    max_bytes: int,
) -> dict[str, Any]:
    refs = assessment.evidence_refs_json or {}
    record_id = assessment.record_id
    rules = _load_by_ids(db, RuleViolation, list(refs.get("rule_violation_ids") or []), record_id)
    stats = _load_by_ids(
        db, StatisticalEvidence, list(refs.get("statistical_evidence_ids") or []), record_id
    )
    ml_rows = _load_by_ids(db, MlEvidence, list(refs.get("ml_evidence_ids") or []), record_id)
    rule_meta = {}
    rule_ids = [row.rule_id for row in rules]
    if rule_ids:
        for item in db.scalars(select(ValidationRule).where(ValidationRule.id.in_(rule_ids))).all():
            rule_meta[item.id] = item
    variables = []
    for row in stats:
        if row.variable and row.variable not in variables:
            variables.append(row.variable)
    for row in rules:
        if row.field and row.field not in variables:
            variables.append(row.field)
    sirl_context = _sirl_slice(db, assessment.batch_id, assessment, variables)
    payload = {
        "unified_assessment": {
            "record_id": assessment.record_id,
            "anomaly_status": classify_assessment(assessment)["anomaly_status"],
            "classification_reason": classify_assessment(assessment)["classification_reason"],
            "risk_score": assessment.risk_score,
            "severity": assessment.severity,
            "evidence_confidence": assessment.confidence,
            "agreement": assessment.agreement,
            "available_sources": list(assessment.available_sources_json or []),
            "missing_sources": list(assessment.missing_sources_json or []),
            "escalation_applied": bool(assessment.escalation_applied),
            "escalation_reason": assessment.escalation_reason,
            "methodology_version": assessment.methodology_version,
            "source_scores": dict(assessment.source_scores_json or {}),
            "source_severities": dict(assessment.source_severities_json or {}),
            "phase6_assessment_available": True,
        },
        "rule_evidence": [_compact_rule(row, rule_meta.get(row.rule_id)) for row in rules],
        "statistical_evidence": [_compact_stat(row) for row in stats],
        "ml_evidence": [_compact_ml(row) for row in ml_rows],
        "sirl_context": sirl_context,
        "instructions": {
            "do_not_override_anomaly_status": True,
            "risk_score_is_authoritative": True,
            "severity_is_authoritative": True,
            "evidence_confidence_is_authoritative": True,
            "agreement_is_authoritative": True,
            "do_not_override_phase6": True,
            "do_not_invent_evidence": True,
            "sirl_context_available": bool(sirl_context.get("available")),
            "if_unavailable_say_unavailable": True,
            "explain_why_flagged_not_the_score": True,
            "primary_and_secondary_reasons_required": True,
        },
        "no_detected_evidence": not (
            bool(rules) or bool(stats) or bool(ml_rows)
        ),
    }
    if _size(payload) <= max_bytes:
        return payload
    payload["sirl_context"] = {"available": payload["sirl_context"].get("available", False)}
    if _size(payload) <= max_bytes:
        return payload
    payload["statistical_evidence"] = payload["statistical_evidence"][:3]
    payload["ml_evidence"] = payload["ml_evidence"][:2]
    payload["rule_evidence"] = payload["rule_evidence"][:4]
    if _size(payload) <= max_bytes:
        return payload
    payload["rule_evidence"] = []
    payload["statistical_evidence"] = []
    payload["ml_evidence"] = []
    payload["no_detected_evidence"] = True
    return payload


def select_clean_context(batch_id: str, record_id: str) -> dict[str, Any]:
    """Explanation-layer context when no Phase 6 assessment exists. Does not invent scores."""
    return {
        "unified_assessment": {
            "record_id": record_id,
            "phase6_assessment_available": False,
            "available_sources": [],
            "missing_sources": ["rules", "statistics", "ml"],
            "note": "No Phase 6 unified assessment exists for this record. Do not invent risk_score or severity.",
        },
        "rule_evidence": [],
        "statistical_evidence": [],
        "ml_evidence": [],
        "sirl_context": {"available": False},
        "no_detected_evidence": True,
        "instructions": {
            "phase6_assessment_available": False,
            "do_not_invent_evidence": True,
            "do_not_override_phase6": True,
            "if_unavailable_say_unavailable": True,
            "explain_why_flagged_not_the_score": True,
            "primary_and_secondary_reasons_required": True,
            "clean_record_do_not_describe_as_suspicious": True,
        },
    }
