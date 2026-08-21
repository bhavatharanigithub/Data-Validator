from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clip_text(value: str, limit: int) -> str:
    return value.strip()[:limit]


_SOURCE_ALIASES = {
    "rules": "rules",
    "rule": "rules",
    "rule_evidence": "rules",
    "rule_violations": "rules",
    "statistics": "statistics",
    "statistical": "statistics",
    "statistical_evidence": "statistics",
    "stats": "statistics",
    "ml": "ml",
    "ml_evidence": "ml",
    "machine_learning": "ml",
    "isolation_forest": "ml",
    "historical": "historical",
    "historical_evidence": "historical",
    "sirl": "historical",
}
_SEVERITIES = {"NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _alias_source(value: str) -> str | None:
    return _SOURCE_ALIASES.get(value.strip().lower().replace(" ", "_"))


def _alias_severity(value: object) -> str:
    if not isinstance(value, str):
        return "NONE"
    token = value.strip().upper()
    return token if token in _SEVERITIES else "NONE"


def _finding_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("finding", "message", "explanation", "text", "summary"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


def _as_string_list(value: object) -> object:
    """Coerce a single string or null into list[str]; leave lists and objects as-is."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return value


def _normalize_evidence_explanations(evidence: object) -> object:
    if not isinstance(evidence, dict):
        return evidence
    items: list[dict[str, str]] = []
    for key, value in evidence.items():
        source = _alias_source(str(key))
        finding = _finding_text(value)
        severity = "NONE"
        if isinstance(value, dict):
            severity = _alias_severity(value.get("severity"))
            nested = value.get("source")
            if isinstance(nested, str) and nested.strip():
                source = _alias_source(nested) or source
        if source and finding:
            items.append({"source": source, "finding": finding, "severity": severity})
    return items


def _as_required_string(value: object) -> object:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return value


def normalize_model_explanation(raw: object) -> dict[str, Any]:
    """Coerce harmless DeepSeek/OpenRouter JSON shapes into ExplanationPayload form.

    Observed live failures:
    - evidence_explanations as a dict of source-key → string
    - limitations as a single string instead of list[str]
    Lists and invalid objects are left unchanged so Pydantic still rejects them.
    """
    if not isinstance(raw, dict):
        return {}
    payload = dict(raw)
    if "evidence_explanations" in payload:
        payload["evidence_explanations"] = _normalize_evidence_explanations(
            payload.get("evidence_explanations")
        )
    if "limitations" in payload:
        payload["limitations"] = _as_string_list(payload.get("limitations"))
    if "key_findings" in payload:
        payload["key_findings"] = _as_string_list(payload.get("key_findings"))
    if "primary_reason" in payload:
        payload["primary_reason"] = _as_required_string(payload.get("primary_reason"))
    if "secondary_reason" in payload:
        payload["secondary_reason"] = _as_required_string(payload.get("secondary_reason"))
    if not payload.get("what_it_means"):
        summary = payload.get("summary")
        if isinstance(summary, str) and summary.strip():
            payload["what_it_means"] = summary
    elif "what_it_means" in payload:
        payload["what_it_means"] = _as_required_string(payload.get("what_it_means"))
    return payload


class EvidenceExplanation(BaseModel):
    source: Literal["rules", "statistics", "ml", "historical"]
    finding: str
    severity: Literal["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

    @field_validator("finding")
    @classmethod
    def _finding(cls, value: str) -> str:
        text = _clip_text(value, 300)
        if not text:
            raise ValueError("finding is required")
        return text


class ExplanationPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary_reason: str
    secondary_reason: str
    summary: str
    what_it_means: str
    key_findings: list[str] = Field(default_factory=list)
    evidence_explanations: list[EvidenceExplanation] = Field(default_factory=list)
    recommended_action: str
    limitations: list[str] = Field(default_factory=list)
    explanation_confidence: float = Field(
        description="Confidence in the explanation (0–1), not probability the record is wrong."
    )

    @field_validator("primary_reason")
    @classmethod
    def _primary(cls, value: str) -> str:
        text = _clip_text(value, 500)
        if not text:
            raise ValueError("primary_reason is required")
        return text

    @field_validator("secondary_reason")
    @classmethod
    def _secondary(cls, value: str) -> str:
        text = _clip_text(value, 500)
        if not text:
            raise ValueError("secondary_reason is required")
        return text

    @field_validator("summary")
    @classmethod
    def _summary(cls, value: str) -> str:
        text = _clip_text(value, 800)
        if not text:
            raise ValueError("summary is required")
        return text

    @field_validator("what_it_means")
    @classmethod
    def _means(cls, value: str) -> str:
        text = _clip_text(value, 800)
        if not text:
            raise ValueError("what_it_means is required")
        return text

    @field_validator("recommended_action")
    @classmethod
    def _action(cls, value: str) -> str:
        text = _clip_text(value, 500)
        if not text:
            raise ValueError("recommended_action is required")
        return text

    @field_validator("key_findings")
    @classmethod
    def _findings(cls, items: list[str]) -> list[str]:
        clipped = [_clip_text(str(item), 300) for item in items if str(item).strip()]
        return clipped[:6]

    @field_validator("evidence_explanations")
    @classmethod
    def _explanations(cls, items: list[EvidenceExplanation]) -> list[EvidenceExplanation]:
        return items[:8]

    @field_validator("limitations")
    @classmethod
    def _limits(cls, items: list[str]) -> list[str]:
        clipped = [_clip_text(str(item), 300) for item in items if str(item).strip()]
        return clipped[:5]

    @field_validator("explanation_confidence")
    @classmethod
    def _confidence(cls, value: float) -> float:
        number = float(value)
        if number < 0.0 or number > 1.0:
            raise ValueError("explanation_confidence must be between 0 and 1")
        return number


class RiskAssessmentSlice(BaseModel):
    risk_score: float | None = None
    severity: str | None = None
    evidence_confidence: float | None = None
    agreement: str | None = None
    escalation_applied: bool = False
    escalation_reason: str | None = None
    available_sources: list[str] = Field(default_factory=list)
    missing_sources: list[str] = Field(default_factory=list)
    methodology_version: str | None = None
    anomaly_status: str | None = None
    classification_reason: str | None = None
    phase6_assessment_available: bool = True


class ExplanationBlock(BaseModel):
    status: str
    reason: str | None = None
    model: str | None = None
    primary_reason: str | None = None
    secondary_reason: str | None = None
    summary: str | None = None
    what_it_means: str | None = None
    key_findings: list[str] = Field(default_factory=list)
    evidence_explanations: list[EvidenceExplanation] = Field(default_factory=list)
    recommended_action: str | None = None
    limitations: list[str] = Field(default_factory=list)
    explanation_confidence: float | None = Field(
        default=None,
        description="Confidence in the explanation (0–1), not probability the record is wrong.",
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ExplanationRunRequest(BaseModel):
    min_risk_score: float | None = None
    severity: str | None = None
    limit: int | None = None
    scope: Literal["priority", "all", "detected"] | None = None


class ExplanationRecordResponse(BaseModel):
    record_id: str
    batch_id: str
    risk_assessment: RiskAssessmentSlice
    explanation: ExplanationBlock


class ExplanationBatchResponse(BaseModel):
    success: bool
    engine: Literal["explanation"] = "explanation"
    batch_id: str
    fusion_run_id: int
    records_explained: int
    available: int = 0
    unavailable: int = 0
    cached: int = 0
    skipped: int = 0
    limit: int | None = None
    min_risk_score: float | None = None
    severity: str | None = None
    scope: str | None = None
    items: list[ExplanationRecordResponse] = Field(default_factory=list)
