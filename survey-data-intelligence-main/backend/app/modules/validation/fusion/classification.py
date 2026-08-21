"""Anomaly classification is separate from Phase 6 risk_score / severity.

ONE authoritative decision function: classify_anomaly_status (alias: classify_anomaly).

Phase 6 may assign HIGH/CRITICAL severity because a record is unusual or because
a demo lookup list did not contain a cluster/enumerator code. That is NOT
confirmation of a data-quality error.

Confirmed anomalies require a deterministic VALIDITY rule, not a catalog lookup.

1. Hard validity rule (age/hours/income/household/required-id/employment-hours)
   → CONFIRMED

2. Statistics and/or ML, and/or demo in_reference lookups, without a validity rule
   → REVIEW if stats/ML are present, else NORMAL if only lookup-list misses
   Lookup-list misses (CLUSTER/DISTRICT/ENUMERATOR_IN_REFERENCE) are not validity errors.

3. No record-level stats/ML/validity evidence
   → NORMAL

risk_score and overall severity are never consulted.
"""

from __future__ import annotations

from typing import Any, Iterable

NORMAL = "NORMAL"
REVIEW = "REVIEW"
CONFIRMED = "CONFIRMED"
ANOMALY = "ANOMALY"
CRITICAL = "CRITICAL"

CONFIRMED_STATUSES = frozenset({CONFIRMED, ANOMALY, CRITICAL})
EXPLAIN_STATUSES = frozenset({REVIEW, CONFIRMED, ANOMALY, CRITICAL})

REASON_NONE = "none"
REASON_HARD_RULE = "hard_rule_violation"
REASON_STATS_AND_ML = "unusual_without_validity_violation"
REASON_STATS_ONLY = "statistics_only_unusual"
REASON_ML_ONLY = "ml_only_unusual"
REASON_LOOKUP = "demo_reference_list_miss"

HARD_VALIDITY_RULE_CODES = frozenset(
    {
        "AGE_MIN",
        "AGE_MAX",
        "WORKING_HOURS_MIN",
        "WORKING_HOURS_MAX",
        "INCOME_NON_NEGATIVE",
        "HOUSEHOLD_SIZE_MIN",
        "EMPLOYED_HAS_HOURS",
        "UNEMPLOYED_ZERO_HOURS",
        "RESPONDENT_ID_REQUIRED",
        "ENUMERATOR_REQUIRED",
        "CLUSTER_REQUIRED",
        "DISTRICT_REQUIRED",
    }
)


def is_lookup_rule_code(rule_code: str | None) -> bool:
    code = str(rule_code or "")
    return code.endswith("_IN_REFERENCE") or "IN_REFERENCE" in code


def is_hard_validity_rule_code(rule_code: str | None) -> bool:
    code = str(rule_code or "")
    if not code or is_lookup_rule_code(code) or code.startswith("TEST_"):
        return False
    return code in HARD_VALIDITY_RULE_CODES


def _score(source_scores: dict[str, float] | None, name: str) -> float:
    try:
        return float((source_scores or {}).get(name) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _ids(refs: dict[str, Any] | None, key: str) -> list:
    values = (refs or {}).get(key) or []
    return list(values) if isinstance(values, list) else []


def _rule_codes(evidence_refs: dict[str, Any] | None) -> list[str]:
    refs = evidence_refs or {}
    codes = refs.get("rule_codes") or []
    return [str(item) for item in codes if item]


def classify_anomaly_status(
    *,
    source_scores: dict[str, float] | None = None,
    source_severities: dict[str, str] | None = None,
    evidence_refs: dict[str, Any] | None = None,
    high_stat_variables: Iterable[str] | None = None,
) -> dict[str, str]:
    """Return anomaly_status from evidence. Ignores risk_score and overall severity."""
    del high_stat_variables, source_severities
    refs = evidence_refs or {}
    codes = _rule_codes(refs)
    has_hard_rule = any(is_hard_validity_rule_code(code) for code in codes)
    has_lookup = any(is_lookup_rule_code(code) for code in codes)
    has_stat = bool(_ids(refs, "statistical_evidence_ids")) or _score(source_scores, "statistics") > 0
    has_ml = bool(_ids(refs, "ml_evidence_ids")) or _score(source_scores, "ml") > 0

    if has_hard_rule:
        return {"anomaly_status": CONFIRMED, "classification_reason": REASON_HARD_RULE}
    if has_stat and has_ml:
        return {"anomaly_status": REVIEW, "classification_reason": REASON_STATS_AND_ML}
    if has_stat:
        return {"anomaly_status": REVIEW, "classification_reason": REASON_STATS_ONLY}
    if has_ml:
        return {"anomaly_status": REVIEW, "classification_reason": REASON_ML_ONLY}
    if has_lookup:
        return {"anomaly_status": NORMAL, "classification_reason": REASON_LOOKUP}
    return {"anomaly_status": NORMAL, "classification_reason": REASON_NONE}


def classify_intelligence(
    *,
    anomaly_status: str,
    detector_types: Iterable[str] | None = None,
) -> dict[str, Any]:
    types = [str(item) for item in (detector_types or []) if item]
    unique = list(dict.fromkeys(types))
    if anomaly_status in CONFIRMED_STATUSES:
        return {
            "intelligence_classification": "VALIDATION_ERROR",
            "primary_detector": "HARD_RULE",
            "detector_count": len(unique) + 1,
            "review_required": True,
        }
    if anomaly_status == REVIEW and len(unique) >= 2:
        return {
            "intelligence_classification": "INVESTIGATION_REQUIRED",
            "primary_detector": unique[0],
            "detector_count": len(unique),
            "review_required": True,
        }
    if anomaly_status == REVIEW:
        return {
            "intelligence_classification": "UNUSUAL_PATTERN",
            "primary_detector": unique[0] if unique else "STATISTICAL_OUTLIER",
            "detector_count": max(len(unique), 1),
            "review_required": True,
        }
    if unique:
        return {
            "intelligence_classification": "INFORMATIONAL",
            "primary_detector": unique[0],
            "detector_count": len(unique),
            "review_required": False,
        }
    return {
        "intelligence_classification": "INFORMATIONAL",
        "primary_detector": None,
        "detector_count": 0,
        "review_required": False,
    }


classify_anomaly = classify_anomaly_status


def hydrate_assessment_rule_codes(db: Any, assessments: list[Any]) -> None:
    """Attach rule_codes from RuleViolation so stale fusion rows reclassify correctly."""
    from sqlalchemy import select

    from app.models import RuleViolation

    needed: set[int] = set()
    for row in assessments:
        refs = getattr(row, "evidence_refs_json", None) or {}
        if refs.get("rule_codes"):
            continue
        for vid in refs.get("rule_violation_ids") or []:
            try:
                needed.add(int(vid))
            except (TypeError, ValueError):
                continue
    found: dict[int, str] = {}
    if needed:
        found = {
            item.id: str(item.rule_code)
            for item in db.scalars(select(RuleViolation).where(RuleViolation.id.in_(needed))).all()
        }
    for row in assessments:
        refs = dict(getattr(row, "evidence_refs_json", None) or {})
        if refs.get("rule_codes"):
            continue
        codes = []
        for vid in refs.get("rule_violation_ids") or []:
            try:
                code = found.get(int(vid))
            except (TypeError, ValueError):
                continue
            if code:
                codes.append(code)
        refs["rule_codes"] = codes
        row.evidence_refs_json = refs


def classify_assessment(assessment: Any) -> dict[str, str]:
    refs = getattr(assessment, "evidence_refs_json", None) or {}
    extra = refs.get("high_stat_variables") if isinstance(refs, dict) else None
    return classify_anomaly_status(
        source_scores=getattr(assessment, "source_scores_json", None),
        source_severities=getattr(assessment, "source_severities_json", None),
        evidence_refs=refs if isinstance(refs, dict) else {},
        high_stat_variables=extra if isinstance(extra, list) else None,
    )


def anomaly_status_of(assessment: Any) -> str:
    return classify_assessment(assessment)["anomaly_status"]


def is_confirmed_anomaly(assessment: Any) -> bool:
    return anomaly_status_of(assessment) in CONFIRMED_STATUSES


def should_auto_explain(assessment: Any) -> bool:
    return anomaly_status_of(assessment) in EXPLAIN_STATUSES


def classification_debug_row(
    *,
    record_id: str,
    fused: dict[str, Any],
    classified: dict[str, str],
    evidence_refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refs = evidence_refs or {}
    return {
        "record_id": record_id,
        "risk_score": fused.get("risk_score"),
        "severity": fused.get("severity"),
        "rule_signal": bool(_rule_codes(refs)) or bool(_ids(refs, "rule_violation_ids")),
        "statistics_signal": bool(_ids(refs, "statistical_evidence_ids"))
        or _score(fused.get("source_scores"), "statistics") > 0,
        "ml_signal": bool(_ids(refs, "ml_evidence_ids")) or _score(fused.get("source_scores"), "ml") > 0,
        "agreement": fused.get("agreement"),
        "anomaly_status": classified.get("anomaly_status"),
        "anomaly_reason": classified.get("classification_reason"),
        "rule_codes": _rule_codes(refs),
    }


def format_classification_table(rows: list[dict[str, Any]]) -> str:
    header = (
        "RECORD | RISK | SEVERITY | RULE | STATISTICS | ML | ANOMALY STATUS | REASON"
    )
    lines = [header]
    for row in sorted(rows, key=lambda item: str(item.get("record_id") or "")):
        lines.append(
            f"{row.get('record_id')} | {row.get('risk_score')} | {row.get('severity')} | "
            f"{row.get('rule_signal')} | {row.get('statistics_signal')} | {row.get('ml_signal')} | "
            f"{row.get('anomaly_status')} | {row.get('anomaly_reason')}"
        )
    return "\n".join(lines)
