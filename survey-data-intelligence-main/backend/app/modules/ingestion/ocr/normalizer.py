"""Field normalization and lightweight pre-import validation for OCR records.

This is deliberately NOT the platform's validation engine (Rules /
Statistics / ML / Fusion). It only answers "can this OCR extraction be
trusted enough to hand to that engine", per FEATURE 7 of the OCR spec.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.modules.ingestion.ocr.constants import (
    KNOWN_GENDERS,
    KNOWN_MARITAL_STATUS,
    NUMERIC_FIELDS,
    STRING_FIELDS,
    confidence_band,
)
from app.modules.ingestion.ocr.parser import RawRecord

_NUMERIC_STRIP_RE = re.compile(r"[^\d.\-]")


@dataclass
class NormalizedRecord:
    record_id: str | None
    name: str | None
    age: int | None
    gender: str | None
    district: str | None
    income: float | int | None
    occupation: str | None
    education: str | None
    marital_status: str | None
    remarks: str | None
    page: int
    needs_review: bool = False
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    field_confidence: dict[str, float | None] = field(default_factory=dict)
    field_confidence_band: dict[str, str] = field(default_factory=dict)
    record_confidence: float | None = None
    record_confidence_band: str = "unknown"

    def as_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "name": self.name,
            "age": self.age,
            "gender": self.gender,
            "district": self.district,
            "income": self.income,
            "occupation": self.occupation,
            "education": self.education,
            "marital_status": self.marital_status,
            "remarks": self.remarks,
            "page": self.page,
        }


def _clean_string(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip(":：").strip()
    return cleaned or None


def _to_number(value: str | None) -> tuple[float | None, bool]:
    """Best-effort numeric coercion. Returns (number, ok)."""
    if value is None:
        return None, True  # absent is fine; only a *present but unparsable* value is an error
    stripped = _NUMERIC_STRIP_RE.sub("", value)
    if not stripped or stripped in {"-", "."}:
        return None, False
    try:
        number = float(stripped)
    except ValueError:
        return None, False
    return number, True


def normalize_record(raw: RawRecord) -> NormalizedRecord:
    values: dict[str, str | None] = {}
    confidence: dict[str, float | None] = {}
    for name in STRING_FIELDS + NUMERIC_FIELDS:
        raw_field = raw.fields.get(name)
        values[name] = _clean_string(raw_field.value) if raw_field else None
        confidence[name] = raw_field.score if raw_field else None

    issues: list[str] = []
    warnings: list[str] = []

    record_id = values["record_id"]
    if not record_id:
        issues.append("Missing Record ID.")

    age_raw = values["age"]
    age, age_ok = _to_number(age_raw)
    if not age_ok:
        issues.append("Age could not be interpreted as a number.")
        age_value: int | None = None
    else:
        age_value = int(age) if age is not None else None
        if age_value is not None and not (0 <= age_value <= 120):
            warnings.append(f"Age {age_value} is outside the plausible range.")

    income_raw = values["income"]
    income_number, income_ok = _to_number(income_raw)
    if not income_ok:
        issues.append("Income could not be interpreted as a number.")
        income: float | int | None = None
    elif income_number is None:
        income = None
    elif income_number == int(income_number):
        income = int(income_number)
    else:
        income = income_number

    if not values["district"]:
        warnings.append("District was not detected.")
    if age_ok and age_value is None:
        warnings.append("Age was not detected.")

    gender = values["gender"]
    if gender and gender.strip().lower() not in KNOWN_GENDERS:
        warnings.append(f"Unrecognized gender value: '{gender}'.")

    marital_status = values["marital_status"]
    if marital_status and marital_status.strip().lower() not in KNOWN_MARITAL_STATUS:
        warnings.append(f"Unrecognized marital status value: '{marital_status}'.")

    field_confidence_band = {k: confidence_band(v) for k, v in confidence.items()}
    scored = [v for v in confidence.values() if v is not None]
    record_confidence = (sum(scored) / len(scored)) if scored else None

    needs_review = bool(issues) or any(
        band == "low" for field_name, band in field_confidence_band.items()
        if values.get(field_name) is not None
    )

    return NormalizedRecord(
        record_id=record_id,
        name=values["name"],
        age=age_value,
        gender=gender,
        district=values["district"],
        income=income,
        occupation=values["occupation"],
        education=values["education"],
        marital_status=marital_status,
        remarks=values["remarks"],
        page=raw.page,
        needs_review=needs_review,
        issues=issues,
        warnings=warnings,
        field_confidence=confidence,
        field_confidence_band=field_confidence_band,
        record_confidence=record_confidence,
        record_confidence_band=confidence_band(record_confidence),
    )


def normalize_records(raw_records: list[RawRecord]) -> list[NormalizedRecord]:
    normalized = [normalize_record(raw) for raw in raw_records]

    seen: dict[str, int] = {}
    for rec in normalized:
        if not rec.record_id:
            continue
        seen[rec.record_id] = seen.get(rec.record_id, 0) + 1
    for rec in normalized:
        if rec.record_id and seen.get(rec.record_id, 0) > 1:
            rec.warnings.append(f"Duplicate Record ID '{rec.record_id}' within this upload.")
            rec.needs_review = True

    return normalized
