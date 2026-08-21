from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

StatusName = Literal[
    "OPEN",
    "IN_REVIEW",
    "REQUIRES_REENUMERATION",
    "ESCALATED",
    "RESOLVED_VALID",
    "RESOLVED_INVALID",
]
ActionName = Literal[
    "REVIEW",
    "VERIFY_SOURCE",
    "REQUEST_REENUMERATION",
    "ESCALATE",
    "MARK_VALID",
    "MARK_INVALID",
]
PriorityName = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class InvestigationCreate(BaseModel):
    batch_id: str
    record_id: str
    validation_run_id: int | None = None
    assigned_to: str | None = None
    priority: PriorityName | None = None


class InvestigationPatch(BaseModel):
    status: StatusName | None = None
    action: ActionName | None = None
    priority: PriorityName | None = None
    assigned_to: str | None = None
    supervisor_notes: str | None = None
    finding: str | None = None
    action_taken: str | None = None
    final_classification: str | None = None


class NoteCreate(BaseModel):
    note: str = Field(min_length=1, max_length=4000)


class InvestigationOut(BaseModel):
    id: int
    batch_id: str
    record_id: str
    validation_run_id: int | None = None
    assigned_to: str | None = None
    status: str
    priority: str
    action: str | None = None
    supervisor_notes: str | None = None
    finding: str | None = None
    action_taken: str | None = None
    final_classification: str | None = None
    created_by: str
    enumerator_id: str | None = None
    district_id: str | None = None
    risk_score: float | None = None
    severity: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    resolved_at: datetime | None = None


class InvestigationListOut(BaseModel):
    items: list[InvestigationOut] = Field(default_factory=list)
    kpis: dict[str, int] = Field(default_factory=dict)


class AuditOut(BaseModel):
    id: int
    investigation_id: int
    user_id: str
    action: str
    previous_status: str | None = None
    new_status: str | None = None
    note: str | None = None
    timestamp: datetime | None = None
