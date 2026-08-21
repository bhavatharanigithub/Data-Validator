from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.validation.fusion.scoring import EVIDENCE_CONFIDENCE_DESCRIPTION


class UnifiedAssessmentOut(BaseModel):
    record_id: str
    enumerator_id: str | None = None
    cluster_id: str | None = None
    district_id: str | None = None
    risk_score: float
    severity: str
    confidence: float = Field(description=EVIDENCE_CONFIDENCE_DESCRIPTION)
    evidence_confidence: float = Field(description=EVIDENCE_CONFIDENCE_DESCRIPTION)
    agreement: str
    available_sources: list[str] = Field(default_factory=list)
    missing_sources: list[str] = Field(default_factory=list)
    source_scores: dict[str, float] = Field(default_factory=dict)
    source_severities: dict[str, str] = Field(default_factory=dict)
    escalation_applied: bool = False
    escalation_reason: str | None = None
    methodology_version: str
    evidence_refs: dict[str, Any] = Field(default_factory=dict)
    anomaly_status: str = "NORMAL"
    classification_reason: str | None = None
    anomaly_reason: str | None = None


class DatasetAssessmentOut(BaseModel):
    """Batch-level statistical context. Not a record-level risk score."""

    scope: Literal["dataset"] = "dataset"
    batch_id: str
    validation_run_id: int
    context_score: float = Field(
        description="Dataset-level statistical context score (0–100). Not a record risk score."
    )
    severity: str
    confidence: float = Field(description=EVIDENCE_CONFIDENCE_DESCRIPTION)
    evidence_confidence: float = Field(description=EVIDENCE_CONFIDENCE_DESCRIPTION)
    agreement: str = "single_source"
    statistical_evidence_ids: list[int] = Field(default_factory=list)
    methodology_version: str
    not_a_record_risk: bool = True


class FusionRunResponse(BaseModel):
    success: bool
    engine: Literal["fusion"] = "fusion"
    batch_id: str
    validation_run_id: int
    status: str
    records_assessed: int
    high: int = 0
    medium: int = 0
    low: int = 0
    critical: int = 0
    confirmed_anomalies: int = 0
    review_signals: int = 0
    available_sources: list[str] = Field(default_factory=list)
    missing_sources: list[str] = Field(default_factory=list)
    methodology_version: str
    weights: dict[str, float] = Field(default_factory=dict)
    has_dataset_assessment: bool = False


class FusionRunDetail(FusionRunResponse):
    items: list[UnifiedAssessmentOut] = Field(
        default_factory=list,
        description="Record-level fused assessments.",
    )
    dataset_assessment: DatasetAssessmentOut | None = Field(
        default=None,
        description="Dataset-level statistical context. Not assigned to records.",
    )
