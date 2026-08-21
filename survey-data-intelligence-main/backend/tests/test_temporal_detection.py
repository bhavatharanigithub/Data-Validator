from __future__ import annotations

import pandas as pd

from app.modules.sirl.profiler import detect_roles
from app.modules.validation.intelligence.temporal import evaluate_temporal


def test_temporal_period_change() -> None:
    rows = []
    for i in range(12):
        rows.append({"respondent_id": f"P1{i}", "survey_round": "R1", "employment_status": "employed", "district_code": "D1"})
    for i in range(12):
        rows.append({"respondent_id": f"P2{i}", "survey_round": "R2", "employment_status": "unemployed", "district_code": "D1"})
    outcome = evaluate_temporal(pd.DataFrame(rows), detect_roles(pd.DataFrame(rows)), {})
    assert outcome.available
    assert any(item.detector_type == "TEMPORAL_CHANGE" for item in outcome.detections)


def test_temporal_insufficient_without_period() -> None:
    frame = pd.DataFrame([{"respondent_id": "R1", "employment_status": "employed"}])
    outcome = evaluate_temporal(frame, detect_roles(frame), {})
    assert outcome.skipped
