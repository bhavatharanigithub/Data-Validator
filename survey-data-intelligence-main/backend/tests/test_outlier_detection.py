from __future__ import annotations

import pandas as pd

from app.modules.validation.statistics.baselines import load_thresholds
from app.modules.validation.statistics.detectors import detect_mad, detect_z_score


def test_mad_handles_zero_variance() -> None:
    values = pd.Series([10.0] * 12)
    ids = pd.Series([str(i) for i in range(12)])
    empty = pd.Series([None] * 12)
    hits = detect_mad(
        values,
        variable="age",
        thresholds=load_thresholds(),
        record_ids=ids,
        enumerator_ids=empty,
        cluster_ids=empty,
        district_ids=empty,
    )
    assert hits == []


def test_z_score_small_n_does_not_crash() -> None:
    values = pd.Series([1.0, 2.0, 3.0])
    ids = pd.Series(["a", "b", "c"])
    empty = pd.Series([None, None, None])
    hits = detect_z_score(
        values,
        variable="age",
        thresholds=load_thresholds(),
        record_ids=ids,
        enumerator_ids=empty,
        cluster_ids=empty,
        district_ids=empty,
    )
    assert hits == []
