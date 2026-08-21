from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EnrichmentPayload(BaseModel):
    contextual_insights: list[str] = Field(default_factory=list)
    important_relationships: list[str] = Field(default_factory=list)
    potential_data_quality_concerns: list[str] = Field(default_factory=list)
    context_summary: str
    confidence: float

    @field_validator("confidence")
    @classmethod
    def _confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class AIHealthResponse(BaseModel):
    configured: bool
    provider_reachable: bool
    model_configured: bool
    status: Literal[
        "ready",
        "not_configured",
        "auth",
        "timeout",
        "rate_limit",
        "provider_error",
        "invalid_response",
        "unreachable",
    ]
