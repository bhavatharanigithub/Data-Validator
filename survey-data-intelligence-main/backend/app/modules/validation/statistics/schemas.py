from typing import Any, Literal

from pydantic import BaseModel, Field


class StatisticalEvidenceOut(BaseModel):
    record_id: str | None = None
    enumerator_id: str | None = None
    cluster_id: str | None = None
    district_id: str | None = None
    variable: str
    detector: str
    scope: str
    observed_value: float | None = None
    baseline_value: float | None = None
    baseline_std: float | None = None
    score: float | None = None
    threshold: float | None = None
    severity: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class StatisticsRunResponse(BaseModel):
    success: bool
    engine: Literal["statistics"] = "statistics"
    batch_id: str
    validation_run_id: int
    status: str
    records_checked: int
    variables_checked: int
    detections: int
    high: int = 0
    medium: int = 0
    low: int = 0
    critical: int = 0
    historical_context_available: bool = False


class StatisticsRunDetail(StatisticsRunResponse):
    items: list[StatisticalEvidenceOut] = Field(default_factory=list)
