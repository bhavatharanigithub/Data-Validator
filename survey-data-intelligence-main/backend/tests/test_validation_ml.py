import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import MlEvidence, RuleViolation, StatisticalEvidence, ValidationRun
from app.modules.sirl.profiler import detect_roles
from app.modules.validation.ml.features import (
    apply_median_imputer,
    fit_median_imputer,
    load_ml_settings,
    select_ml_features,
)
from app.modules.validation.ml.model import (
    infer,
    ml_severity,
    model_configuration,
    normalize_anomaly_scores,
    train_isolation_forest,
)
from tests.conftest import SAMPLES


def test_numeric_feature_selection_excludes_identifiers_and_text() -> None:
    frame = pd.read_csv(SAMPLES / "survey_ml_demo.csv")
    names = select_ml_features(frame, detect_roles(frame))
    assert "respondent_id" not in names
    assert "enumerator_id" not in names
    assert "cluster_id" not in names
    assert "district_code" not in names
    assert "notes" not in names
    assert "sex" not in names
    assert "employment_status" not in names
    assert "age" in names
    assert "working_hours" in names
    assert "income" in names
    assert "household_size" in names


def test_median_imputation_does_not_use_zero() -> None:
    frame = pd.DataFrame({"a": [10.0, 20.0, None, 30.0], "b": [4.0, 6.0, 8.0, None]})
    medians = fit_median_imputer(frame, ["a", "b"])
    assert medians["a"] == 20.0
    assert medians["b"] == 6.0
    matrix, used = apply_median_imputer(frame, ["a", "b"], medians)
    assert used == ["a", "b"]
    assert matrix[2, 0] == 20.0
    assert matrix[3, 1] == 6.0
    assert 0.0 not in (matrix[2, 0], matrix[3, 1])


def test_insufficient_features() -> None:
    frame = pd.DataFrame(
        {
            "respondent_id": ["R1", "R2"],
            "notes": ["hello", "world"],
        }
    )
    assert select_ml_features(frame) == []


def test_isolation_forest_is_deterministic_and_scores_extreme_row_highest() -> None:
    settings = load_ml_settings()
    typical = np.tile(np.array([[32.0, 40.0, 15000.0, 4.0]]), (40, 1))
    extreme = np.array([[80.0, 160.0, 80000.0, 1.0]])
    X = np.vstack([typical, extreme])
    first = train_isolation_forest(X, settings)
    second = train_isolation_forest(X, settings)
    _, scores_a, labels_a = infer(first, X)
    _, scores_b, labels_b = infer(second, X)
    assert np.allclose(scores_a, scores_b)
    assert np.array_equal(labels_a, labels_b)
    assert int(np.argmax(scores_a)) == 40


def test_anomaly_score_normalization_and_severity() -> None:
    raw = np.array([0.0, 1.0, 2.0, 10.0])
    scores = normalize_anomaly_scores(raw, lo=0.0, hi=10.0)
    assert scores.tolist() == [0.0, 10.0, 20.0, 100.0]
    assert np.all((scores >= 0) & (scores <= 100))
    settings = load_ml_settings()
    assert ml_severity(settings.score_medium - 1, settings) == "LOW"
    assert ml_severity(settings.score_medium, settings) == "MEDIUM"
    assert ml_severity(settings.score_high, settings) == "HIGH"
    config = model_configuration(settings)
    assert config["algorithm"] == "isolation_forest"
    assert config["random_state"] == settings.random_state
    assert "sklearn_version" in config


def test_identical_training_scores_normalize_to_zero() -> None:
    scores = normalize_anomaly_scores(np.array([3.0, 3.0, 3.0]), lo=3.0, hi=3.0)
    assert scores.tolist() == [0.0, 0.0, 0.0]


def _tiny_feature_csv() -> bytes:
    return (
        "respondent_id,feat_alpha,feat_beta,notes\n"
        "T1,1,2,text\n"
        "T2,1,2,text\n"
        "T3,1,2,text\n"
    ).encode()


def test_insufficient_training_data_api(client: TestClient) -> None:
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("tiny_ml.csv", _tiny_feature_csv(), "text/csv")},
    )
    assert ingest.status_code == 200
    batch_id = ingest.json()["batch_id"]
    result = client.post(f"/api/validation/ml/run/{batch_id}")
    assert result.status_code == 200
    body = result.json()
    assert body["success"] is True
    assert body["engine"] == "ml"
    assert body["status"] == "insufficient_data"
    assert body["anomalies"] == 0
    assert body["training_source"] == "none"


def test_ml_api_persistence_metadata_and_idempotency(client: TestClient) -> None:
    content = (SAMPLES / "survey_ml_demo.csv").read_bytes()
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_ml_demo.csv", content, "text/csv")},
    )
    assert ingest.status_code == 200
    batch_id = ingest.json()["batch_id"]

    extras = [
        item
        for item in client.get("/api/validation/rules").json()
        if item.get("enabled") and not item.get("is_sample")
    ]
    for item in extras:
        client.patch(f"/api/validation/rules/{item['id']}/disable")
    try:
        rules = client.post(f"/api/validation/rules/run/{batch_id}").json()
        assert rules["success"] is True
        assert rules["engine"] == "rules"
        assert rules["violations"] == 0
        stats = client.post(f"/api/validation/statistics/run/{batch_id}").json()
        assert stats["success"] is True
        assert stats["engine"] == "statistics"
        first = client.post(f"/api/validation/ml/run/{batch_id}")
        assert first.status_code == 200
        body = first.json()
        assert body["success"] is True
        assert body["engine"] == "ml"
        assert body["status"] == "COMPLETED"
        assert body["records_checked"] == 40
        assert body["features_used"] >= 2
        assert "age" in body["feature_names"]
        assert "household_size" in body["feature_names"]
        assert body["training_source"] in {"historical", "current_batch"}
        assert body["training_records"] >= 32
        assert body["model_configuration"]["algorithm"] == "isolation_forest"
        assert body["model_configuration"]["random_state"] == 42
        assert "sklearn_version" in body["model_configuration"]
        assert (
            body["high"] + body["medium"] + body["low"] == body["anomalies"]
        )
        detail = client.get(f"/api/validation/ml/runs/{body['validation_run_id']}")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["feature_names"] == body["feature_names"]
        assert len(payload["items"]) == body["anomalies"]
        for item in payload["items"]:
            assert item["prediction"] == "anomaly"
            assert 0 <= item["anomaly_score"] <= 100
            assert item["model_type"] == "isolation_forest"
            assert item["feature_names"] == body["feature_names"]
            assert "score_note" in item["evidence"]

        db = SessionLocal()
        try:
            rule_count = len(
                db.scalars(select(RuleViolation).where(RuleViolation.batch_id == batch_id)).all()
            )
            stat_count = len(
                db.scalars(
                    select(StatisticalEvidence).where(StatisticalEvidence.batch_id == batch_id)
                ).all()
            )
            ml_count = len(db.scalars(select(MlEvidence).where(MlEvidence.batch_id == batch_id)).all())
            assert rule_count == rules["violations"]
            assert stat_count == stats["detections"]
            assert ml_count == body["anomalies"]
        finally:
            db.close()

        second = client.post(f"/api/validation/ml/run/{batch_id}").json()
        assert second["anomalies"] == body["anomalies"]
        db = SessionLocal()
        try:
            ml_rows = db.scalars(select(MlEvidence).where(MlEvidence.batch_id == batch_id)).all()
            assert len(ml_rows) == second["anomalies"]
            ml_runs = db.scalars(
                select(ValidationRun).where(
                    ValidationRun.batch_id == batch_id,
                    ValidationRun.validation_type == "ml",
                )
            ).all()
            assert len(ml_runs) == 1
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
            assert len(db.scalars(select(RuleViolation).where(RuleViolation.batch_id == batch_id)).all()) == rule_count
            assert len(
                db.scalars(
                    select(StatisticalEvidence).where(StatisticalEvidence.batch_id == batch_id)
                ).all()
            ) == stat_count
        finally:
            db.close()
    finally:
        for item in extras:
            client.patch(f"/api/validation/rules/{item['id']}/enable")


def test_ml_nonexistent_batch(client: TestClient) -> None:
    response = client.post("/api/validation/ml/run/BATCH_NOPE")
    assert response.status_code == 404
