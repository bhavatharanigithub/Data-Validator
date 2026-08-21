from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProfileCounts(BaseModel):
    dataset: bool
    variables: int
    records: int
    enumerators: int
    clusters: int
    districts: int


class ProfileRunResponse(BaseModel):
    success: bool
    batch_id: str
    status: str
    records: int
    variables: int
    profiles_created: ProfileCounts
    historical_context_available: bool
    reused_existing: bool = False
    ai_enrichment_status: Literal["available", "unavailable"] = "unavailable"
    ai_enrichment_reason: str | None = None


class AiEnrichment(BaseModel):
    enabled: bool = False
    enriched: bool = False
    status: Literal["available", "unavailable"] = "unavailable"
    reason: str | None = None
    contextual_insights: list[str] = Field(default_factory=list)
    important_relationships: list[str] = Field(default_factory=list)
    potential_data_quality_concerns: list[str] = Field(default_factory=list)
    context_summary: str | None = None
    confidence: float | None = None


def unavailable_enrichment(reason: str = "not_configured") -> AiEnrichment:
    return AiEnrichment(
        enabled=False,
        enriched=False,
        status="unavailable",
        reason=reason,
    )


class SirlContext(BaseModel):
    batch_id: str
    dataset_context: dict[str, Any] = Field(default_factory=dict)
    variable_context: dict[str, Any] = Field(default_factory=dict)
    record_context: list[dict[str, Any]] = Field(default_factory=list)
    enumerator_context: dict[str, Any] = Field(default_factory=dict)
    cluster_context: dict[str, Any] = Field(default_factory=dict)
    district_context: dict[str, Any] = Field(default_factory=dict)
    historical_context: dict[str, Any] = Field(default_factory=dict)
    ai_enrichment: AiEnrichment = Field(default_factory=unavailable_enrichment)
    profiled_at: datetime | None = None
