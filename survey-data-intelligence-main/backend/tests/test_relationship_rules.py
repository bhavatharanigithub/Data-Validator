from __future__ import annotations

import pandas as pd

from app.modules.sirl.profiler import detect_roles
from app.modules.validation.intelligence.relationships import evaluate_relationships


def test_relationship_age_marital_is_unusual_not_fraud() -> None:
    frame = pd.DataFrame(
        [
            {"respondent_id": "R1", "age": 16, "marital_status": "married", "employment_status": "employed", "working_hours": 40, "income": 12000},
            {"respondent_id": "R2", "age": 34, "marital_status": "never married", "employment_status": "employed", "working_hours": 40, "income": 12000},
        ]
    )
    outcome = evaluate_relationships(frame, detect_roles(frame), {})
    assert any(item.detector_type == "REL_AGE_MARITAL" for item in outcome.detections)
    assert all("fraud" not in item.explanation.lower() for item in outcome.detections)


def test_relationship_unemployed_high_income_is_review() -> None:
    frame = pd.DataFrame(
        [{"respondent_id": "R1", "age": 40, "employment_status": "unemployed", "income": 90000, "working_hours": 0}]
    )
    outcome = evaluate_relationships(frame, detect_roles(frame), {})
    assert any(item.detector_type == "REL_INCOME_EMPLOYMENT" for item in outcome.detections)
    assert all(item.classification == "UNUSUAL_PATTERN" for item in outcome.detections)
