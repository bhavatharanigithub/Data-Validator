from __future__ import annotations

import pandas as pd

from app.modules.sirl.profiler import detect_roles
from app.modules.validation.intelligence.enumerator import evaluate_enumerators


def test_enumerator_employment_deviation() -> None:
    rows = []
    for i in range(12):
        rows.append({"respondent_id": f"A{i}", "enumerator_id": "E1", "district_code": "D1", "employment_status": "unemployed" if i < 6 else "employed", "working_hours": 0 if i < 6 else 40, "income": 1000})
    for i in range(12):
        rows.append({"respondent_id": f"B{i}", "enumerator_id": "E2", "district_code": "D1", "employment_status": "employed", "working_hours": 40, "income": 12000})
    outcome = evaluate_enumerators(pd.DataFrame(rows), detect_roles(pd.DataFrame(rows)), {})
    assert outcome.available
    assert any(item.detector_type == "ENUMERATOR_DEVIATION" for item in outcome.detections)


def test_enumerator_unavailable_without_id() -> None:
    frame = pd.DataFrame([{"respondent_id": "R1", "age": 30}])
    outcome = evaluate_enumerators(frame, detect_roles(frame), {})
    assert outcome.skipped
