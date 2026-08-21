from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

StageName = Literal[
    "INGESTION",
    "PARQUET",
    "SIRL",
    "RULES",
    "STATISTICS",
    "INTELLIGENCE",
    "ML",
    "FUSION",
    "EXPLANATION",
]
PipelineStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "PARTIAL"]
StageStatus = Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED", "UNAVAILABLE", "SKIPPED"]


class PipelineRunRequest(BaseModel):
    rerun: bool = False


class StageOut(BaseModel):
    stage: str
    status: StageStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    engine_run_id: int | None = None
    records_processed: int | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class PipelineRunOut(BaseModel):
    pipeline_run_id: int
    batch_id: str
    status: PipelineStatus
    current_stage: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    is_active: bool = False
    reused: bool = False
    stages: list[StageOut] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineStatusLite(BaseModel):
    batch_id: str
    status: str
    current_stage: str | None = None
    progress: int | None = None
    pipeline_run_id: int | None = None
