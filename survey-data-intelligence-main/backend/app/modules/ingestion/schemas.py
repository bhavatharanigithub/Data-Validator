from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IngestResponse(BaseModel):
    success: bool
    source: Literal["csv", "esigma"]
    rows: int
    columns: list[str]
    batch_id: str
    schema_version: str
    dtypes: dict[str, str]
    storage: Literal["parquet"]
    parquet_path: str
    status: str = "QUEUED"
    pipeline_run_id: int | None = None
    reused: bool = False


class ESigmaIngestRequest(BaseModel):
    path: str | None = None


class ESigmaPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str | None = None
    records: list[dict[str, Any]] = Field(min_length=1)
