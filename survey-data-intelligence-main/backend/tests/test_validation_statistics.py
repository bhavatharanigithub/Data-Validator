from datetime import UTC, datetime
from io import BytesIO

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    Batch,
    BatchStatus,
    HistoricalProfile,
    RuleViolation,
    StatisticalEvidence,
    ValidationRun,
    VariableProfile,
)
from app.modules.sirl.profiler import detect_roles
from app.modules.validation.statistics.baselines import (
    StatsThresholds,
    eligible_variables,
    load_historical_baselines,
)
from app.modules.validation.statistics.detectors import (
    detect_historical_shift,
    detect_iqr,
    detect_z_score,
    iqr_severity,
    z_severity,
)
from tests.conftest import SAMPLES


def _thresholds(**overrides: float | int) -> StatsThresholds:
    payload = dict(
        z_medium=2.0,
        z_high=3.0,
        iqr_multiplier=1.5,
        iqr_outer_multiplier=3.0,
        min_observations=8,
        min_group_observations=5,
        std_epsilon=1e-9,
        historical_relative_medium=0.5,
        historical_relative_high=1.0,
    )
    payload.update(overrides)
    return StatsThresholds(**payload)


def _ids(n: int) -> dict:
    index = pd.RangeIndex(n)
    none = pd.Series([None] * n, index=index)
    return {
        "record_ids": pd.Series([f"R{i}" for i in range(n)], index=index),
        "enumerator_ids": none,
        "cluster_ids": none,
        "district_ids": none,
    }


def test_z_score_calculation_and_thresholds() -> None:
    thresholds = _thresholds()
    assert z_severity(1.9, thresholds) is None
    assert z_severity(2.0, thresholds) == "MEDIUM"
    assert z_severity(2.9, thresholds) == "MEDIUM"
    assert z_severity(3.0, thresholds) == "HIGH"
    values = pd.Series([10.0] * 9 + [40.0])
    detections = detect_z_score(values, variable="working_hours", thresholds=thresholds, **_ids(10))
    scores = [item["score"] for item in detections]
    assert detections
    assert all(abs(score) >= 2.0 for score in scores)
    high = [item for item in detections if item["record_id"] == "R9"]
    assert high
    observed = float(high[0]["observed_value"])
    mean = float(high[0]["baseline_value"])
    std = float(high[0]["baseline_std"])
    assert abs(high[0]["score"] - (observed - mean) / std) < 1e-9
    assert high[0]["severity"] in {"MEDIUM", "HIGH"}


def test_zero_standard_deviation_skips() -> None:
    values = pd.Series([12.0] * 10)
    detections = detect_z_score(
        values, variable="age", thresholds=_thresholds(), **_ids(10)
    )
    assert detections == []


def test_insufficient_observations_skip() -> None:
    values = pd.Series([10.0, 10.0, 100.0])
    assert detect_z_score(values, variable="age", thresholds=_thresholds(), **_ids(3)) == []
    assert detect_iqr(values, variable="age", thresholds=_thresholds(), **_ids(3)) == []


def test_iqr_outlier_detection() -> None:
    values = pd.Series([float(i) for i in range(1, 9)] + [100.0])
    detections = detect_iqr(values, variable="income", thresholds=_thresholds(), **_ids(9))
    assert detections
    flagged = next(item for item in detections if item["record_id"] == "R8")
    assert flagged["detector"] == "iqr"
    assert flagged["observed_value"] == 100.0
    assert flagged["severity"] in {"MEDIUM", "HIGH"}
    assert iqr_severity(100.0, 0.0, 10.0, -10.0, 20.0) == "HIGH"
    assert iqr_severity(11.0, 0.0, 10.0, -20.0, 30.0) == "MEDIUM"
    assert iqr_severity(5.0, 0.0, 10.0, -20.0, 30.0) is None


def test_missing_numeric_values_are_not_detected() -> None:
    values = pd.Series([10.0] * 8 + [None, 40.0])
    detections = detect_z_score(
        values, variable="working_hours", thresholds=_thresholds(), **_ids(10)
    )
    assert "R8" not in {item["record_id"] for item in detections}


def test_identifier_exclusion() -> None:
    frame = pd.read_csv(SAMPLES / "survey_stats_demo.csv")
    roles = detect_roles(frame)
    names = eligible_variables(frame, roles)
    assert "respondent_id" not in names
    assert "enumerator_id" not in names
    assert "cluster_id" not in names
    assert "district_code" not in names
    assert "notes" not in names
    assert "working_hours" in names
    assert "age" in names
    assert "income" in names


def test_historical_shift_and_unavailable() -> None:
    thresholds = _thresholds()
    assert detect_historical_shift({"synth_unemployment_pct": 40.0}, {}, thresholds) == []
    relative = detect_historical_shift(
        {"synth_unemployment_pct": 40.0},
        {"synth_unemployment_pct": {"mean": 8.0, "std": None, "source_batch_id": "PRIOR"}},
        thresholds,
    )
    assert len(relative) == 1
    assert relative[0]["detector"] == "historical_shift"
    assert relative[0]["observed_value"] == 40.0
    assert relative[0]["baseline_value"] == 8.0
    assert relative[0]["severity"] == "HIGH"
    assert relative[0]["evidence_json"]["metric"] == "relative_change"
    z_based = detect_historical_shift(
        {"synth_unemployment_pct": 40.0},
        {"synth_unemployment_pct": {"mean": 8.0, "std": 1.0, "source_batch_id": "PRIOR"}},
        thresholds,
    )
    assert z_based[0]["score"] == 32.0
    assert z_based[0]["severity"] == "HIGH"


def test_group_level_deviation() -> None:
    from app.modules.validation.statistics.detectors import detect_group_z_score

    hours = [40.0] * 11 + [100.0]
    frame = pd.DataFrame(
        {
            "working_hours": hours,
            "enumerator_id": ["E12"] * 12,
            "cluster_id": ["C01"] * 12,
            "district_code": ["1101"] * 12,
            "respondent_id": [f"R{i}" for i in range(12)],
        }
    )
    numeric = frame["working_hours"]
    ids = {
        "record_ids": frame["respondent_id"],
        "enumerator_ids": frame["enumerator_id"],
        "cluster_ids": frame["cluster_id"],
        "district_ids": frame["district_code"],
    }
    thresholds = _thresholds(min_group_observations=5)
    enumerator = detect_group_z_score(
        frame, numeric, variable="working_hours", group_col="enumerator_id",
        scope="enumerator", thresholds=thresholds, **ids,
    )
    cluster = detect_group_z_score(
        frame, numeric, variable="working_hours", group_col="cluster_id",
        scope="cluster", thresholds=thresholds, **ids,
    )
    district = detect_group_z_score(
        frame, numeric, variable="working_hours", group_col="district_code",
        scope="district", thresholds=thresholds, **ids,
    )
    assert any(item["record_id"] == "R11" and item["scope"] == "enumerator" for item in enumerator)
    assert any(item["record_id"] == "R11" and item["scope"] == "cluster" for item in cluster)
    assert any(item["record_id"] == "R11" and item["scope"] == "district" for item in district)
    assert enumerator[0]["evidence_json"]["group_id"] == "E12"


def _disable_extra_rules(client: TestClient) -> list[int]:
    extras = [
        item
        for item in client.get("/api/validation/rules").json()
        if item.get("enabled") and not item.get("is_sample")
    ]
    for item in extras:
        client.patch(f"/api/validation/rules/{item['id']}/disable")
    return [item["id"] for item in extras]


def _enable_rules(client: TestClient, ids: list[int]) -> None:
    for rule_id in ids:
        client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_stats_demo_is_rule_valid_but_statistically_unusual(client: TestClient) -> None:
    extra_ids = _disable_extra_rules(client)
    content = (SAMPLES / "survey_stats_demo.csv").read_bytes()
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_stats_demo.csv", content, "text/csv")},
    )
    assert ingest.status_code == 200
    batch_id = ingest.json()["batch_id"]
    try:
        rules = client.post(f"/api/validation/rules/run/{batch_id}").json()
        assert rules["success"] is True
        assert rules["engine"] == "rules"
        assert rules["violations"] == 0
        stats = client.post(f"/api/validation/statistics/run/{batch_id}").json()
        assert stats["success"] is True
        assert stats["engine"] == "statistics"
        assert stats["records_checked"] == 24
        assert stats["detections"] >= 1
        assert (
            stats["high"] + stats["medium"] + stats["low"] + stats["critical"]
            == stats["detections"]
        )
        detail = client.get(f"/api/validation/statistics/runs/{stats['validation_run_id']}").json()
        hours = [
            item
            for item in detail["items"]
            if item["variable"] == "working_hours" and item["record_id"] == "R212"
        ]
        assert hours
        sample = hours[0]
        assert sample["severity"] in {"MEDIUM", "HIGH"}
        evidence = sample["evidence"]
        assert evidence["detector"] in {"z_score", "iqr", "group_z_score"}
        assert evidence["observed_value"] == 100
        assert "baseline_mean" in evidence
        assert "score" in evidence
        assert "threshold" in evidence
        assert "scope" in evidence
        db = SessionLocal()
        try:
            stored = db.scalars(
                select(StatisticalEvidence).where(StatisticalEvidence.batch_id == batch_id)
            ).all()
            assert len(stored) == stats["detections"]
            rule_rows = db.scalars(
                select(RuleViolation).where(RuleViolation.batch_id == batch_id)
            ).all()
            assert rule_rows == []
            rule_runs = db.scalars(
                select(ValidationRun).where(
                    ValidationRun.batch_id == batch_id,
                    ValidationRun.validation_type == "rules",
                )
            ).all()
            stat_runs = db.scalars(
                select(ValidationRun).where(
                    ValidationRun.batch_id == batch_id,
                    ValidationRun.validation_type == "statistics",
                )
            ).all()
            assert len(rule_runs) == 1
            assert len(stat_runs) == 1
        finally:
            db.close()
    finally:
        _enable_rules(client, extra_ids)


def test_clean_sample_has_no_statistical_detections(client: TestClient, sample_csv_bytes: bytes) -> None:
    db = SessionLocal()
    try:
        prior_batches = db.scalars(select(Batch.batch_id)).all()
    finally:
        db.close()
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", sample_csv_bytes, "text/csv")},
    )
    batch_id = ingest.json()["batch_id"]
    stats = client.post(f"/api/validation/statistics/run/{batch_id}").json()
    assert stats["success"] is True
    assert stats["records_checked"] == 4
    if not prior_batches:
        assert stats["detections"] == 0


def test_statistics_run_is_idempotent(client: TestClient) -> None:
    content = (SAMPLES / "survey_stats_demo.csv").read_bytes()
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_stats_demo.csv", content, "text/csv")},
        params={"auto_pipeline": "false"},
    )
    batch_id = ingest.json()["batch_id"]
    first = client.post(f"/api/validation/statistics/run/{batch_id}").json()
    second = client.post(f"/api/validation/statistics/run/{batch_id}").json()
    assert first["detections"] == second["detections"]
    db = SessionLocal()
    try:
        stored = db.scalars(
            select(StatisticalEvidence).where(StatisticalEvidence.batch_id == batch_id)
        ).all()
        assert len(stored) == second["detections"]
        runs = db.scalars(
            select(ValidationRun).where(
                ValidationRun.batch_id == batch_id,
                ValidationRun.validation_type == "statistics",
            )
        ).all()
        assert len(runs) == 1
        rule_runs = db.scalars(
            select(ValidationRun).where(
                ValidationRun.batch_id == batch_id,
                ValidationRun.validation_type == "rules",
            )
        ).all()
        assert rule_runs == []
    finally:
        db.close()


def test_historical_baseline_from_prior_batch(client: TestClient) -> None:
    prior_id = "BATCH_SYNTH_HISTORICAL"
    db = SessionLocal()
    try:
        existing = db.scalars(select(Batch).where(Batch.batch_id == prior_id)).first()
        if existing is None:
            db.add(
                Batch(
                    batch_id=prior_id,
                    source="csv",
                    survey_code="DEMO",
                    status=BatchStatus.PROFILED,
                    schema_version="v1",
                    created_at=datetime.now(UTC),
                )
            )
            db.add(
                HistoricalProfile(
                    batch_id=prior_id,
                    schema_version="v1",
                    grain="dataset",
                    grain_key=prior_id,
                    stats_json={"numeric_measures": ["synth_unemployment_pct"]},
                    created_at=datetime.now(UTC),
                )
            )
            db.add(
                VariableProfile(
                    batch_id=prior_id,
                    variable_name="synth_unemployment_pct",
                    dtype="float64",
                    kind="numeric",
                    profile_json={
                        "kind": "numeric",
                        "mean": 8.0,
                        "standard_deviation": 1.0,
                        "variable_name": "synth_unemployment_pct",
                    },
                    created_at=datetime.now(UTC),
                )
            )
            db.commit()
    finally:
        db.close()

    frame = pd.read_csv(SAMPLES / "survey_stats_demo.csv")
    frame["synth_unemployment_pct"] = 40.0
    buffer = BytesIO()
    frame.to_csv(buffer, index=False)
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_stats_hist.csv", buffer.getvalue(), "text/csv")},
    )
    batch_id = ingest.json()["batch_id"]
    stats = client.post(f"/api/validation/statistics/run/{batch_id}").json()
    assert stats["historical_context_available"] is True
    detail = client.get(f"/api/validation/statistics/runs/{stats['validation_run_id']}").json()
    shifts = [
        item
        for item in detail["items"]
        if item["detector"] == "historical_shift" and item["variable"] == "synth_unemployment_pct"
    ]
    assert shifts
    assert shifts[0]["observed_value"] == 40.0
    assert shifts[0]["baseline_value"] == 8.0


def test_historical_baseline_unavailable_for_unknown_variable() -> None:
    db = SessionLocal()
    try:
        baseline, available = load_historical_baselines(
            db, "BATCH_DOES_NOT_EXIST", ["definitely_missing_variable_xyz"]
        )
        assert baseline == {}
        assert available is False
    finally:
        db.close()
