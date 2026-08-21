"""Deterministic fusion-v1-prototype formulas.

Rule severity → 0–100: NONE=0, LOW=25, MEDIUM=50, HIGH=80, CRITICAL=100
Statistical severity → 0–100: NONE=0, LOW=30, MEDIUM=60, HIGH=90, CRITICAL=100
ML contribution: anomaly_score used as-is (0–100), not a probability.

Aggregation of multiple detections for one record and source:
    min(100, strongest + remainder * sum(remaining))
    remainder default 0.20
One HIGH rule (80) stays 80. Two HIGH: 80 + 0.20*80 = 96. Capped at 100.

Weighted risk uses only AVAILABLE sources. Weights are renormalized:
    risk = sum(score_s * (w_s / sum(w_available)))

Overall severity from risk_score:
    0–24 LOW, 25–49 MEDIUM, 50–74 HIGH, 75–100 CRITICAL

Escalation: if >= N available sources have HIGH or CRITICAL source severity,
overall severity is at least HIGH and risk_score is at least the HIGH threshold.

Confidence / evidence_confidence 0–100:
    Deterministic evidence confidence, not probability, not a CI,
    and not P(the record is wrong).
    1 source: 45; 2 sources: 70; 3 sources: 88
    +8 strong agreement, +4 moderate, -22 mixed
    +4 if historical/reference context metadata is present
    clipped to [0, 100]

Agreement:
    0 sources: insufficient
    1 source: single_source
    2+ with two HIGH/CRITICAL: strong
    2+ with score spread > agreement_spread: mixed
    2+ all scores 0: strong (agree on none)
    otherwise: moderate
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings

SOURCES = ("rules", "statistics", "ml")
HIGH_SEVERITIES = frozenset({"HIGH", "CRITICAL"})
EVIDENCE_CONFIDENCE_DESCRIPTION = (
    "Deterministic evidence confidence (0–100), not probability."
)

RULE_SEVERITY_SCORES = {
    "NONE": 0.0,
    "LOW": 25.0,
    "MEDIUM": 50.0,
    "HIGH": 80.0,
    "CRITICAL": 100.0,
}
STAT_SEVERITY_SCORES = {
    "NONE": 0.0,
    "LOW": 30.0,
    "MEDIUM": 60.0,
    "HIGH": 90.0,
    "CRITICAL": 100.0,
}


@dataclass(frozen=True)
class FusionSettings:
    weights: dict[str, float]
    remainder: float
    escalation_min_sources: int
    risk_medium: float
    risk_high: float
    risk_critical: float
    agreement_spread: float
    methodology_version: str


def load_fusion_settings() -> FusionSettings:
    return FusionSettings(
        weights={
            "rules": float(settings.fusion_weight_rules),
            "statistics": float(settings.fusion_weight_statistics),
            "ml": float(settings.fusion_weight_ml),
        },
        remainder=float(settings.fusion_aggregation_remainder),
        escalation_min_sources=int(settings.fusion_escalation_min_sources),
        risk_medium=float(settings.fusion_risk_medium_threshold),
        risk_high=float(settings.fusion_risk_high_threshold),
        risk_critical=float(settings.fusion_risk_critical_threshold),
        agreement_spread=float(settings.fusion_agreement_spread),
        methodology_version=str(settings.fusion_methodology_version),
    )


def normalize_rule_severity(severity: str | None) -> float:
    if not severity:
        return 0.0
    return RULE_SEVERITY_SCORES.get(severity.upper(), 0.0)


def normalize_stat_severity(severity: str | None) -> float:
    if not severity:
        return 0.0
    return STAT_SEVERITY_SCORES.get(severity.upper(), 0.0)


def normalize_ml_score(anomaly_score: float | None) -> float:
    if anomaly_score is None:
        return 0.0
    return float(min(100.0, max(0.0, anomaly_score)))


def aggregate_scores(scores: list[float], remainder: float) -> float:
    if not scores:
        return 0.0
    ordered = sorted(scores, reverse=True)
    combined = ordered[0] + remainder * sum(ordered[1:])
    return float(min(100.0, combined))


def strongest_severity(severities: list[str]) -> str:
    rank = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    if not severities:
        return "NONE"
    return max((item.upper() for item in severities), key=lambda item: rank.get(item, 0))


def weighted_risk(source_scores: dict[str, float], available: list[str], weights: dict[str, float]) -> float:
    active = [name for name in available if name in weights]
    total = sum(weights[name] for name in active)
    if total <= 0:
        return 0.0
    risk = sum(source_scores.get(name, 0.0) * (weights[name] / total) for name in active)
    return float(min(100.0, max(0.0, risk)))


def risk_severity(risk_score: float, cfg: FusionSettings) -> str:
    if risk_score >= cfg.risk_critical:
        return "CRITICAL"
    if risk_score >= cfg.risk_high:
        return "HIGH"
    if risk_score >= cfg.risk_medium:
        return "MEDIUM"
    return "LOW"


def evidence_agreement(
    available: list[str],
    source_scores: dict[str, float],
    source_severities: dict[str, str],
    spread_limit: float,
) -> str:
    if len(available) == 0:
        return "insufficient"
    if len(available) == 1:
        return "single_source"
    high_count = sum(1 for name in available if source_severities.get(name) in HIGH_SEVERITIES)
    values = [source_scores.get(name, 0.0) for name in available]
    spread = max(values) - min(values)
    if high_count >= 2:
        return "strong"
    if max(values) == 0:
        return "strong"
    if spread > spread_limit:
        return "mixed"
    return "moderate"


def confidence_score(
    available: list[str],
    agreement: str,
    historical_context: bool,
) -> float:
    n = len(available)
    if n == 0:
        return 10.0
    base = {1: 45.0, 2: 70.0, 3: 88.0}.get(n, 45.0)
    if agreement == "strong":
        base += 8.0
    elif agreement == "moderate":
        base += 4.0
    elif agreement == "mixed":
        base -= 22.0
    if historical_context:
        base += 4.0
    return float(min(100.0, max(0.0, base)))


def apply_escalation(
    risk_score: float,
    severity: str,
    source_severities: dict[str, str],
    available: list[str],
    cfg: FusionSettings,
) -> tuple[float, str, bool, str | None]:
    high_count = sum(
        1 for name in available if source_severities.get(name) in HIGH_SEVERITIES
    )
    if high_count < cfg.escalation_min_sources:
        return risk_score, severity, False, None
    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    if rank.get(severity, 0) >= rank["HIGH"]:
        return (
            risk_score,
            severity,
            True,
            "Two independent evidence sources produced HIGH severity.",
        )
    return (
        max(risk_score, cfg.risk_high),
        "HIGH",
        True,
        "Two independent evidence sources produced HIGH severity.",
    )


def fuse_record(
    *,
    available: list[str],
    source_scores: dict[str, float],
    source_severities: dict[str, str],
    cfg: FusionSettings,
    historical_context: bool = False,
) -> dict:
    missing = [name for name in SOURCES if name not in available]
    if not available:
        return {
            "risk_score": 0.0,
            "severity": "LOW",
            "confidence": 10.0,
            "evidence_confidence": 10.0,
            "agreement": "insufficient",
            "available_sources": [],
            "missing_sources": list(SOURCES),
            "source_scores": {},
            "source_severities": {},
            "escalation_applied": False,
            "escalation_reason": None,
            "methodology_version": cfg.methodology_version,
        }
    risk = weighted_risk(source_scores, available, cfg.weights)
    severity = risk_severity(risk, cfg)
    agreement = evidence_agreement(available, source_scores, source_severities, cfg.agreement_spread)
    risk, severity, escalated, reason = apply_escalation(
        risk, severity, source_severities, available, cfg
    )
    confidence = confidence_score(available, agreement, historical_context)
    return {
        "risk_score": round(risk, 2),
        "severity": severity,
        "confidence": round(confidence, 2),
        "evidence_confidence": round(confidence, 2),
        "agreement": agreement,
        "available_sources": list(available),
        "missing_sources": missing,
        "source_scores": {name: round(source_scores.get(name, 0.0), 2) for name in available},
        "source_severities": {name: source_severities.get(name, "NONE") for name in available},
        "escalation_applied": escalated,
        "escalation_reason": reason,
        "methodology_version": cfg.methodology_version,
    }


def fuse_dataset_context(
    *,
    statistical_severities: list[str],
    statistical_evidence_ids: list[int],
    cfg: FusionSettings,
    historical_context: bool = False,
) -> dict | None:
    """Dataset-level statistical context. Not a record risk score and not assigned to records."""
    if not statistical_severities:
        return None
    scores = [normalize_stat_severity(item) for item in statistical_severities]
    context_score = aggregate_scores(scores, cfg.remainder)
    severity = strongest_severity(statistical_severities)
    confidence = confidence_score(["statistics"], "single_source", historical_context)
    return {
        "scope": "dataset",
        "context_score": round(context_score, 2),
        "severity": severity,
        "confidence": round(confidence, 2),
        "evidence_confidence": round(confidence, 2),
        "agreement": "single_source",
        "statistical_evidence_ids": list(statistical_evidence_ids),
        "methodology_version": cfg.methodology_version,
        "not_a_record_risk": True,
    }
