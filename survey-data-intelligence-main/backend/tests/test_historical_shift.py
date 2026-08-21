from __future__ import annotations

import pandas as pd

from app.db import SessionLocal
from app.modules.sirl.profiler import detect_roles
from app.modules.validation.intelligence.historical import evaluate_distribution_shift


def test_historical_shift_skips_without_priors() -> None:
    db = SessionLocal()
    try:
        frame = pd.DataFrame([{"respondent_id": "R1", "employment_status": "employed"}] * 10)
        outcome = evaluate_distribution_shift(db, "BATCH_NONE", frame, detect_roles(frame), {})
        assert isinstance(outcome.detections, list)
    finally:
        db.close()
