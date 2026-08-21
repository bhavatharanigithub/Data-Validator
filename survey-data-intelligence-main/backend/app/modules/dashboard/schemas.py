from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DemoLoginRequest(BaseModel):
    username: str
    password: str
    role: Literal["FIELD_SUPERVISOR", "SURVEY_ADMIN"] = "FIELD_SUPERVISOR"


class DemoLoginResponse(BaseModel):
    success: bool
    demo: bool = True
    notice: str
    username: str
    role: str
    token: str


class DemoAuthStatus(BaseModel):
    demo: bool = True
    notice: str
    default_username: str
    password_configured: bool


class PipelineStage(BaseModel):
    id: str
    label: str
    status: Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED", "UNAVAILABLE"]
    timestamp: datetime | None = None
    record_count: int | None = None
    detail: str | None = None


class PipelineResponse(BaseModel):
    batch_id: str
    source: str
    stages: list[PipelineStage]


class OverviewResponse(BaseModel):
    available: bool
    batch_id: str | None = None
    survey_code: str | None = None
    total_records: int | None = None
    processed: int | None = None
    high_risk: int | None = None
    medium_risk: int | None = None
    low_risk: int | None = None
    clean: int | None = None
    critical: int | None = None
    confirmed_anomalies: int | None = None
    review_signals: int | None = None
    anomaly_rate: float | None = None
    enumerators: int | None = None
    fusion_run_id: int | None = None
    fusion_status: str | None = None
    validation_errors: int | None = None
    unusual_patterns: int | None = None
    investigation_required: int | None = None
    enumerator_alerts: int | None = None
    cluster_alerts: int | None = None
    temporal_alerts: int | None = None
    geographic_alerts: int | None = None
    relationship_alerts: int | None = None
    quality_signals: dict[str, int] | None = None
    pipeline_status: str | None = None
    current_stage: str | None = None
    active_pipeline_run_id: int | None = None
    message: str | None = None


class AnomalyRow(BaseModel):
    batch_id: str
    record_id: str
    risk_score: float
    severity: str
    agreement: str
    evidence_confidence: float
    enumerator_id: str | None = None
    cluster_id: str | None = None
    district_id: str | None = None
    available_sources: list[str] = Field(default_factory=list)
    missing_sources: list[str] = Field(default_factory=list)
    source_scores: dict[str, float] = Field(default_factory=dict)
    source_severities: dict[str, str] = Field(default_factory=dict)
    escalation_applied: bool = False
    anomaly_status: str = "NORMAL"
    classification_reason: str | None = None
    anomaly_reason: str | None = None
    intelligence_classification: str | None = None
    primary_detector: str | None = None
    detector_count: int | None = None
    review_required: bool = False
    detectors: list[str] = Field(default_factory=list)
    ai_explanation_status: str = "not_generated"
    ai_explanation_reason: str | None = None


class AnomalyListResponse(BaseModel):
    available: bool
    batch_id: str | None = None
    fusion_run_id: int | None = None
    total: int = 0
    page: int = 1
    page_size: int = 25
    items: list[AnomalyRow] = Field(default_factory=list)
    message: str | None = None


class EvidenceItem(BaseModel):
    source: str
    code: str | None = None
    detector: str | None = None
    field: str | None = None
    variable: str | None = None
    observed_value: Any = None
    expected: str | None = None
    score: float | None = None
    threshold: float | None = None
    severity: str | None = None
    model_type: str | None = None
    anomaly_score: float | None = None
    message: str | None = None


class SourceCard(BaseModel):
    source: str
    status: str
    score: float | None = None
    severity: str | None = None
    detections: int = 0
    items: list[EvidenceItem] = Field(default_factory=list)


class RecordDetailResponse(BaseModel):
    available: bool
    batch_id: str
    record_id: str
    assessment: AnomalyRow | None = None
    sources: list[SourceCard] = Field(default_factory=list)
    explanation: dict[str, Any] | None = None
    sirl_available: bool = False
    escalation_applied: bool = False
    escalation_reason: str | None = None
    message: str | None = None


class GroupRow(BaseModel):
    id: str
    district_id: str | None = None
    cluster_id: str | None = None
    records: int
    high_risk: int
    medium_risk: int
    low_risk: int
    critical: int
    anomaly_rate: float | None = None
    missingness_rate: float | None = None
    enumerators: int | None = None


class GroupListResponse(BaseModel):
    available: bool
    batch_id: str | None = None
    grain: str
    items: list[GroupRow] = Field(default_factory=list)
    message: str | None = None
    view: str = "current_batch"
    batch_count: int | None = None


class GroupDetailResponse(GroupListResponse):
    group_id: str
    high_risk_records: list[AnomalyRow] = Field(default_factory=list)
    common_sources: list[str] = Field(default_factory=list)


class ESigmaStatusResponse(BaseModel):
    mock_mode: bool
    configured: bool
    status: str
    notice: str
