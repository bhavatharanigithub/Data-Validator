from typing import Any, Literal

from pydantic import BaseModel, Field


class MlEvidenceOut(BaseModel):
    record_id: str | None = None
    enumerator_id: str | None = None
    cluster_id: str | None = None
    district_id: str | None = None
    model_type: str
    model_version: str
    feature_names: list[str] = Field(default_factory=list)
    anomaly_score: float
    raw_model_score: float | None = None
    prediction: str
    severity: str
    training_source: str
    training_records: int
    evidence: dict[str, Any] = Field(default_factory=dict)


class MlRunResponse(BaseModel):
    success: bool
    engine: Literal["ml"] = "ml"
    batch_id: str
    validation_run_id: int
    status: str
    records_checked: int
    features_used: int
    feature_names: list[str] = Field(default_factory=list)
    anomalies: int
    high: int = 0
    medium: int = 0
    low: int = 0
    training_source: str
    historical_data_available: bool = False
    training_records: int = 0
    model_configuration: dict[str, Any] = Field(default_factory=dict)


class MlRunDetail(MlRunResponse):
    items: list[MlEvidenceOut] = Field(default_factory=list)
