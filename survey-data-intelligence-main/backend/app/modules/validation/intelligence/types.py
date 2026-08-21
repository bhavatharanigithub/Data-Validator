"""Shared detection payload. Unusual ≠ invalid."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VALIDATION_ERROR = "VALIDATION_ERROR"
UNUSUAL_PATTERN = "UNUSUAL_PATTERN"
INVESTIGATION_REQUIRED = "INVESTIGATION_REQUIRED"
INFORMATIONAL = "INFORMATIONAL"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

HOUSEHOLD_CANDIDATES = ("household_id", "hh_id")
MARITAL_CANDIDATES = ("marital_status", "marital", "marriage_status")
EDUCATION_CANDIDATES = ("education", "education_level", "edu")
ROLE_CANDIDATES = ("household_role", "relation_to_head", "relationship")
PERIOD_CANDIDATES = ("survey_round", "visit", "ref_period", "collected_at", "period")
EMPLOYMENT_CANDIDATES = ("employment_status", "emp_status", "activity_status")
INCOME_CANDIDATES = ("income",)
HOURS_CANDIDATES = ("working_hours", "hours")
AGE_CANDIDATES = ("age",)
SEX_CANDIDATES = ("sex", "gender")


@dataclass
class Detection:
    entity_type: str
    entity_id: str
    detector_type: str
    category: str
    classification: str
    severity: str
    explanation: str
    record_id: str | None = None
    enumerator_id: str | None = None
    cluster_id: str | None = None
    district_id: str | None = None
    household_id: str | None = None
    field_name: str | None = None
    observed_value: float | None = None
    expected_value: float | None = None
    deviation: float | None = None
    baseline_type: str | None = None
    confidence: float = 0.6
    review_required: bool = True
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectorOutcome:
    available: bool
    skipped: bool = False
    reason: str | None = None
    detections: list[Detection] = field(default_factory=list)


def first_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    lookup = {name.lower(): name for name in columns}
    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]
    return None
