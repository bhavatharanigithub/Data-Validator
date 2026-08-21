from __future__ import annotations

import pandas as pd

from app.modules.sirl.profiler import detect_roles
from app.modules.validation.intelligence.patterns import evaluate_patterns


def test_pattern_cluster_similarity() -> None:
    rows = []
    for i in range(10):
        rows.append(
            {
                "respondent_id": f"S{i}",
                "cluster_id": "C88",
                "age": 30,
                "sex": "M",
                "education": "secondary",
                "employment_status": "employed",
                "working_hours": 40,
                "income": 15000,
            }
        )
    outcome = evaluate_patterns(pd.DataFrame(rows), detect_roles(pd.DataFrame(rows)), {})
    assert any(item.detector_type == "CLUSTER_PATTERN" for item in outcome.detections)
    assert all("fabricat" not in item.explanation.lower() for item in outcome.detections)
