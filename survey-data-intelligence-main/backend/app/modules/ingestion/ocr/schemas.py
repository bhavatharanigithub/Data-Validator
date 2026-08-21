from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OcrRecordOut(BaseModel):
    record_id: str | None = None
    name: str | None = None
    age: int | None = None
    gender: str | None = None
    district: str | None = None
    income: float | int | None = None
    occupation: str | None = None
    education: str | None = None
    marital_status: str | None = None
    remarks: str | None = None
    page: int = 1
    needs_review: bool = False
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    field_confidence: dict[str, float | None] = Field(default_factory=dict)
    field_confidence_band: dict[str, str] = Field(default_factory=dict)
    record_confidence: float | None = None
    record_confidence_band: str = "unknown"


class OcrPreviewResponse(BaseModel):
    success: bool
    source: str = "photo_pdf"
    filename: str
    pages: int
    records_detected: int
    records: list[OcrRecordOut]
    records_needing_review: int
    raw_text: str


class OcrImportRecordIn(BaseModel):
    """What the frontend sends back after the user reviews/edits records.

    Deliberately loose (``extra='ignore'``) so re-posting the exact preview
    payload -- confidence fields and all -- just works without the client
    having to strip anything out.
    """

    model_config = {"extra": "ignore"}

    record_id: str | None = None
    name: str | None = None
    age: int | None = None
    gender: str | None = None
    district: str | None = None
    income: float | int | None = None
    occupation: str | None = None
    education: str | None = None
    marital_status: str | None = None
    remarks: str | None = None
    page: int | None = None


class OcrImportRequest(BaseModel):
    filename: str
    records: list[OcrImportRecordIn] = Field(min_length=1)


class OcrImportResponse(BaseModel):
    success: bool
    source: str = "photo_pdf"
    batch_id: str
    rows: int
    columns: list[str]
    schema_version: str
    records_imported: int
    records_requiring_review: int
    status: str
    pipeline_run_id: int | None = None
    reused: bool = False


class OcrErrorDetail(BaseModel):
    detail: str
    extra: dict[str, Any] | None = None
