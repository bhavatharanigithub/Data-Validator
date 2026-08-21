"""Constants for the Photo / PDF OCR ingestion path.

Kept separate from ``app.config.Settings`` so the OCR feature can be tuned
without touching unrelated configuration. Anything that should be
overridable at runtime is still sourced from ``settings`` where practical;
values here are the parser/normalizer's internal vocabulary and are not
meant to be exposed as environment variables.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# File handling
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp"}
)

SUPPORTED_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
)

# Hard ceiling on how many PDF pages will be OCR'd in a single request.
# Protects the CPU-only OCR pipeline from pathological uploads.
MAX_PDF_PAGES = 50

# ---------------------------------------------------------------------------
# OCR confidence bands (recognition confidence, NOT data correctness)
# ---------------------------------------------------------------------------

CONFIDENCE_HIGH_THRESHOLD = 0.90
CONFIDENCE_MEDIUM_THRESHOLD = 0.70


def confidence_band(score: float | None) -> str:
    """Map a PaddleOCR recognition score to a coarse confidence band."""
    if score is None:
        return "unknown"
    if score >= CONFIDENCE_HIGH_THRESHOLD:
        return "high"
    if score >= CONFIDENCE_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Canonical survey record fields
# ---------------------------------------------------------------------------
# This mirrors the generic ingestion pipeline: any column name survives, but
# the OCR parser targets the household-survey vocabulary the platform's
# sample forms use. Aliases are matched case-insensitively, whole-line.

FIELD_ALIASES: list[tuple[str, list[str]]] = [
    ("record_id", ["record id", "record no", "record number", "id"]),
    ("name", ["name", "respondent name"]),
    ("age", ["age"]),
    ("gender", ["gender", "sex"]),
    ("district", ["district", "district name"]),
    ("income", ["income", "monthly income", "household income"]),
    ("occupation", ["occupation", "profession"]),
    ("education", ["education", "education level", "qualification"]),
    ("marital_status", ["marital status"]),
    ("remarks", ["remarks", "remark", "notes"]),
]

REQUIRED_FIELDS = ("record_id",)
STRING_FIELDS = ("record_id", "name", "gender", "district", "occupation", "education", "marital_status", "remarks")
NUMERIC_FIELDS = ("age", "income")

KNOWN_GENDERS = {"male", "female", "other", "transgender"}
KNOWN_MARITAL_STATUS = {"married", "unmarried", "single", "divorced", "widowed", "separated"}

# Labels that appear on survey forms but are intentionally NOT part of the
# canonical record (e.g. signature blocks). Left unmatched by FIELD_ALIASES
# so the parser naturally skips them without special-casing.
