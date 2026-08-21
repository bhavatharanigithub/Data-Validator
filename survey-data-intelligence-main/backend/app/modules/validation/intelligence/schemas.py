from typing import Any

from pydantic import BaseModel, Field


class IntelligenceRunResponse(BaseModel):
    success: bool
    engine: str = "intelligence"
    batch_id: str
    validation_run_id: int
    status: str
    records_checked: int
    detections: int
    available: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    reason: dict[str, str] = Field(default_factory=dict)


class DetectorConfigOut(BaseModel):
    id: int
    detector_id: str
    name: str
    category: str
    description: str | None = None
    enabled: bool
    severity: str
    thresholds_json: dict[str, Any] | None = None


class DetectorConfigUpdate(BaseModel):
    enabled: bool | None = None
    severity: str | None = None
    thresholds_json: dict[str, Any] | None = None


class QualityDetectionOut(BaseModel):
    id: int
    batch_id: str
    entity_type: str
    entity_id: str
    record_id: str | None = None
    enumerator_id: str | None = None
    cluster_id: str | None = None
    district_id: str | None = None
    household_id: str | None = None
    detector_type: str
    category: str
    classification: str
    severity: str
    confidence: float
    review_required: bool
    field_name: str | None = None
    observed_value: float | None = None
    expected_value: float | None = None
    deviation: float | None = None
    baseline_type: str | None = None
    explanation: str
    evidence_json: dict[str, Any] = Field(default_factory=dict)


class AnomalySummaryOut(BaseModel):
    total: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    validation_errors: int = 0
    unusual_patterns: int = 0
    investigation_required: int = 0
    informational: int = 0
    by_detector: dict[str, int] = Field(default_factory=dict)
    by_entity: dict[str, int] = Field(default_factory=dict)
    detectors_available: list[str] = Field(default_factory=list)
    detectors_skipped: list[str] = Field(default_factory=list)
    skip_reasons: dict[str, str] = Field(default_factory=dict)
