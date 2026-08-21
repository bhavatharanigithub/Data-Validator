from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DetectorConfig

DEFAULT_DETECTORS = [
    {
        "detector_id": "REL_AGE_MARITAL",
        "name": "Age / marital status",
        "category": "RELATIONSHIP",
        "description": "Young age combined with married status is unusual and requires review.",
        "severity": "MEDIUM",
        "thresholds_json": {"min_marriage_age": 18},
    },
    {
        "detector_id": "REL_AGE_EDUCATION",
        "name": "Age / education",
        "category": "RELATIONSHIP",
        "description": "Very young age with postgraduate education is an unusual combination.",
        "severity": "MEDIUM",
        "thresholds_json": {"postgraduate_min_age": 20},
    },
    {
        "detector_id": "REL_EMPLOYMENT_HOURS",
        "name": "Employment / working hours",
        "category": "RELATIONSHIP",
        "description": "Not-working status with substantial working hours is inconsistent.",
        "severity": "MEDIUM",
        "thresholds_json": {"not_working_hours_threshold": 10},
    },
    {
        "detector_id": "REL_AGE_HOUSEHOLD_ROLE",
        "name": "Age / household role",
        "category": "RELATIONSHIP",
        "description": "Very young household head is an unusual pattern.",
        "severity": "MEDIUM",
        "thresholds_json": {"min_head_age": 16},
    },
    {
        "detector_id": "REL_INCOME_EMPLOYMENT",
        "name": "Income / employment",
        "category": "RELATIONSHIP",
        "description": "Unemployed status with unusually high income needs review, not automatic rejection.",
        "severity": "MEDIUM",
        "thresholds_json": {"unemployed_high_income": 80000},
    },
    {
        "detector_id": "REL_HOURS_EMPLOYMENT",
        "name": "Working hours / employment",
        "category": "RELATIONSHIP",
        "description": "Positive working hours with inconsistent employment status.",
        "severity": "MEDIUM",
        "thresholds_json": {"positive_hours": 0},
    },
    {
        "detector_id": "REL_HOUSEHOLD_CONSISTENCY",
        "name": "Household consistency",
        "category": "RELATIONSHIP",
        "description": "Multiple household heads or impossible household structures.",
        "severity": "MEDIUM",
        "thresholds_json": {},
    },
    {
        "detector_id": "REL_ARITHMETIC",
        "name": "Arithmetic consistency",
        "category": "RELATIONSHIP",
        "description": "Component fields should approximately sum to a total when those fields exist.",
        "severity": "LOW",
        "thresholds_json": {"tolerance": 1.0},
    },
    {
        "detector_id": "ENUMERATOR_DEVIATION",
        "name": "Enumerator employment deviation",
        "category": "ENUMERATOR",
        "description": "Enumerator employment rate vs batch and district baselines.",
        "severity": "MEDIUM",
        "thresholds_json": {"pp_threshold": 0.25, "min_records": 8},
    },
    {
        "detector_id": "ENUMERATOR_MISSINGNESS",
        "name": "Enumerator missingness deviation",
        "category": "ENUMERATOR",
        "description": "Unusually high or extremely low missingness can both be unusual.",
        "severity": "MEDIUM",
        "thresholds_json": {"pp_threshold": 0.08, "min_records": 8},
    },
    {
        "detector_id": "ENUMERATOR_ENTROPY",
        "name": "Enumerator response diversity",
        "category": "ENUMERATOR",
        "description": "Concentrated categorical responses relative to the batch.",
        "severity": "MEDIUM",
        "thresholds_json": {"entropy_ratio": 0.45, "min_records": 8},
    },
    {
        "detector_id": "PATTERN_ENUMERATOR_SIMILARITY",
        "name": "Enumerator repeated responses",
        "category": "PATTERN",
        "description": "Near-identical canonical signatures within an enumerator.",
        "severity": "MEDIUM",
        "thresholds_json": {"share_threshold": 0.6, "min_records": 8},
    },
    {
        "detector_id": "TEMPORAL_CHANGE",
        "name": "Period-over-period change",
        "category": "TEMPORAL",
        "description": "Large period change in employment/unemployment rates.",
        "severity": "MEDIUM",
        "thresholds_json": {"pp_threshold": 0.08, "min_period_n": 8},
    },
    {
        "detector_id": "GEOGRAPHIC_CLUSTER",
        "name": "Cluster geographic deviation",
        "category": "GEOGRAPHIC",
        "description": "Cluster metrics vs district/national baselines.",
        "severity": "MEDIUM",
        "thresholds_json": {"pp_threshold": 0.25, "min_records": 6},
    },
    {
        "detector_id": "GEOGRAPHIC_DISTRICT",
        "name": "District geographic deviation",
        "category": "GEOGRAPHIC",
        "description": "District metrics vs national baseline.",
        "severity": "MEDIUM",
        "thresholds_json": {"pp_threshold": 0.2, "min_records": 8},
    },
    {
        "detector_id": "CLUSTER_PATTERN",
        "name": "Cluster response similarity",
        "category": "PATTERN",
        "description": "High concentration of similar responses within a cluster.",
        "severity": "MEDIUM",
        "thresholds_json": {"share_threshold": 0.7, "min_records": 8},
    },
    {
        "detector_id": "DISTRIBUTION_SHIFT",
        "name": "Historical distribution shift",
        "category": "HISTORICAL",
        "description": "KS/PSI/TVD against a prior batch profile when available.",
        "severity": "MEDIUM",
        "thresholds_json": {"psi_threshold": 0.25, "ks_threshold": 0.35, "tvd_threshold": 0.35},
    },
    {
        "detector_id": "STAT_MAD",
        "name": "Robust MAD outlier",
        "category": "STATISTICAL",
        "description": "Median absolute deviation robust z-score on numeric measures.",
        "severity": "MEDIUM",
        "thresholds_json": {},
    },
]


def seed_detectors(db: Session) -> None:
    existing = {row.detector_id for row in db.scalars(select(DetectorConfig)).all()}
    for item in DEFAULT_DETECTORS:
        if item["detector_id"] in existing:
            continue
        db.add(DetectorConfig(**item, enabled=True))
    db.commit()


def enabled_map(db: Session) -> dict[str, DetectorConfig]:
    seed_detectors(db)
    return {row.detector_id: row for row in db.scalars(select(DetectorConfig)).all()}


def is_enabled(configs: dict[str, DetectorConfig], detector_id: str) -> bool:
    row = configs.get(detector_id)
    return bool(row is None or row.enabled)


def thresholds(configs: dict[str, DetectorConfig], detector_id: str) -> dict:
    row = configs.get(detector_id)
    payload = dict((row.thresholds_json or {}) if row else {})
    return payload
