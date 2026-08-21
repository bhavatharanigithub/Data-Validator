from datetime import datetime

from pydantic import BaseModel


class BatchResponse(BaseModel):
    batch_id: str
    source: str
    status: str
    schema_version: str | None
    records: int | None
    columns: int | None
    parquet_path: str | None
    created_at: datetime
    completed_at: datetime | None
    error_message: str | None
    survey_code: str | None = None
    pipeline_status: str | None = None
    pipeline_run_id: int | None = None
    pipeline_version: str | None = None
    confirmed_issues: int | None = None
    investigation_signals: int | None = None


class BatchListResponse(BaseModel):
    items: list[BatchResponse]
