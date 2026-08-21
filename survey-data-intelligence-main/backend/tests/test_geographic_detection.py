from __future__ import annotations

import pandas as pd

from app.modules.sirl.profiler import detect_roles
from app.modules.validation.intelligence.geographic import evaluate_geographic


def test_geographic_cluster_deviation() -> None:
    rows = []
    for i in range(10):
        rows.append({"respondent_id": f"C{i}", "cluster_id": "C01", "district_code": "D1", "employment_status": "employed"})
    for i in range(10):
        rows.append({"respondent_id": f"X{i}", "cluster_id": "C99", "district_code": "D1", "employment_status": "unemployed"})
    outcome = evaluate_geographic(pd.DataFrame(rows), detect_roles(pd.DataFrame(rows)), {})
    assert any(item.detector_type == "GEOGRAPHIC_CLUSTER" for item in outcome.detections)


def test_geographic_unavailable_without_geo() -> None:
    frame = pd.DataFrame([{"respondent_id": "R1", "age": 20}])
    outcome = evaluate_geographic(frame, detect_roles(frame), {})
    assert outcome.skipped
