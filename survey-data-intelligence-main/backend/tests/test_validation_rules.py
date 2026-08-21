from uuid import uuid4

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Batch, RuleViolation, ValidationRule, ValidationRun
from app.modules.ingestion.csv_ingest import ingest_csv_bytes
from app.modules.validation.rules.engine import evaluate_frame
from app.modules.validation.rules.evaluator import Predicate, violation_mask
from app.modules.validation.rules.operators import predicate_holds
from app.modules.validation.rules.repository import load_reference_lookup
from tests.conftest import SAMPLES


def test_rule_crud_and_enable_disable(client: TestClient) -> None:
    created = client.post(
        "/api/validation/rules",
        json={
            "rule_code": f"TEST_AGE_EQ_{uuid4().hex[:8]}",
            "name": "Age equals 34",
            "field": "age",
            "operator": "equals",
            "value": 34,
            "severity": "LOW",
        },
    )
    assert created.status_code == 200
    rule_id = created.json()["id"]
    listed = client.get("/api/validation/rules")
    assert listed.status_code == 200
    payload = listed.json()
    assert isinstance(payload, list)
    assert any(item.get("id") == rule_id for item in payload)
    fetched = client.get(f"/api/validation/rules/{rule_id}")
    assert fetched.status_code == 200
    updated = client.put(
        f"/api/validation/rules/{rule_id}",
        json={"name": "Age equals thirty-four", "severity": "MEDIUM"},
    )
    assert updated.json()["name"] == "Age equals thirty-four"
    disabled = client.patch(f"/api/validation/rules/{rule_id}/disable")
    assert disabled.json()["enabled"] is False
    enabled = client.patch(f"/api/validation/rules/{rule_id}/enable")
    assert enabled.json()["enabled"] is True
    deleted = client.delete(f"/api/validation/rules/{rule_id}")
    assert deleted.status_code == 200


def test_invalid_severity_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/validation/rules",
        json={
            "rule_code": "BAD_SEV",
            "name": "bad",
            "field": "age",
            "operator": "equals",
            "value": 1,
            "severity": "EXTREME",
        },
    )
    assert response.status_code == 422


def test_cross_field_requires_second_field(client: TestClient) -> None:
    response = client.post(
        "/api/validation/rules",
        json={
            "rule_code": "BAD_CROSS",
            "name": "bad",
            "field": "age",
            "operator": "field_greater_than_field",
            "value": None,
        },
    )
    assert response.status_code == 422


def test_invalid_operator_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/validation/rules",
        json={
            "rule_code": "BAD_OP",
            "name": "bad",
            "field": "age",
            "operator": "eval",
            "value": 1,
        },
    )
    assert response.status_code == 422


def test_vectorized_numeric_and_null_operators() -> None:
    series = pd.Series([10, 20, None], dtype="Int64")
    assert predicate_holds(series, "greater_than", 15).tolist() == [False, True, False]
    assert predicate_holds(series, "is_null").tolist() == [False, False, True]
    assert predicate_holds(series, "is_not_null").tolist() == [True, True, False]
    assert predicate_holds(series, "between", [10, 15]).tolist() == [True, False, False]


def test_blank_operators_treat_whitespace_as_missing() -> None:
    series = pd.Series([None, "", "   ", "C01"])
    assert predicate_holds(series, "is_null").tolist() == [True, False, False, False]
    assert predicate_holds(series, "is_not_null").tolist() == [False, True, True, True]
    assert predicate_holds(series, "is_blank").tolist() == [True, True, True, False]
    assert predicate_holds(series, "is_not_blank").tolist() == [False, False, False, True]


def test_categorical_and_cross_field() -> None:
    frame = pd.DataFrame({"sex": ["F", "M", "F"], "a": [5, 1, 3], "b": [2, 2, 3]})
    eq = predicate_holds(frame["sex"], "equals", "F")
    assert eq.tolist() == [True, False, True]
    gt = predicate_holds(frame["a"], "field_greater_than_field", other=frame["b"])
    assert gt.tolist() == [True, False, False]


def _ingest_invalid(client: TestClient) -> str:
    content = (SAMPLES / "survey_invalid.csv").read_bytes()
    response = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_invalid.csv", content, "text/csv")},
        params={"auto_pipeline": "false"},
    )
    assert response.status_code == 200
    return response.json()["batch_id"]


def test_run_rules_on_invalid_sample(client: TestClient) -> None:
    batch_id = _ingest_invalid(client)
    result = client.post(f"/api/validation/rules/run/{batch_id}")
    assert result.status_code == 200
    body = result.json()
    assert body["success"] is True
    assert body["engine"] == "rules"
    assert body["records_checked"] == 10
    assert body["violations"] >= 8
    run_id = body["validation_run_id"]
    detail = client.get(f"/api/validation/runs/{run_id}")
    codes = {item["rule_code"] for item in detail.json()["items"]}
    assert "AGE_MIN" in codes
    assert "AGE_MAX" in codes
    assert "WORKING_HOURS_MAX" in codes
    assert "INCOME_NON_NEGATIVE" in codes
    assert "EMPLOYED_HAS_HOURS" in codes
    assert "RESPONDENT_ID_REQUIRED" in codes
    assert "CLUSTER_IN_REFERENCE" in codes
    assert "DISTRICT_IN_REFERENCE" in codes
    assert "ENUMERATOR_IN_REFERENCE" in codes
    assert (
        body["critical_severity"]
        + body["high_severity"]
        + body["medium_severity"]
        + body["low_severity"]
        == body["violations"]
    )
    db = SessionLocal()
    try:
        stored = db.scalars(select(RuleViolation).where(RuleViolation.batch_id == batch_id)).all()
        assert len(stored) == body["violations"]
    finally:
        db.close()


def test_rerun_does_not_duplicate(client: TestClient) -> None:
    batch_id = _ingest_invalid(client)
    first = client.post(f"/api/validation/rules/run/{batch_id}").json()
    second = client.post(f"/api/validation/rules/run/{batch_id}").json()
    assert first["violations"] == second["violations"]
    db = SessionLocal()
    try:
        stored = db.scalars(select(RuleViolation).where(RuleViolation.batch_id == batch_id)).all()
        assert len(stored) == second["violations"]
        runs = db.scalars(select(ValidationRun).where(ValidationRun.batch_id == batch_id)).all()
        assert len(runs) == 1
    finally:
        db.close()


def test_disabled_rules_are_skipped(client: TestClient) -> None:
    batch_id = _ingest_invalid(client)
    rules = client.get("/api/validation/rules").json()
    age_max = next(item for item in rules if item["rule_code"] == "AGE_MAX")
    client.patch(f"/api/validation/rules/{age_max['id']}/disable")
    result = client.post(f"/api/validation/rules/run/{batch_id}").json()
    detail = client.get(f"/api/validation/runs/{result['validation_run_id']}").json()
    codes = {item["rule_code"] for item in detail["items"]}
    assert "AGE_MAX" not in codes
    client.patch(f"/api/validation/rules/{age_max['id']}/enable")


def test_missing_field_skips_rule_not_run(client: TestClient) -> None:
    created = client.post(
        "/api/validation/rules",
        json={
                "rule_code": f"MISSING_COL_{uuid4().hex}",
            "name": "Missing column",
            "field": "does_not_exist",
            "operator": "equals",
            "value": 1,
            "severity": "LOW",
        },
    )
    assert created.status_code == 200
    batch_id = _ingest_invalid(client)
    result = client.post(f"/api/validation/rules/run/{batch_id}")
    assert result.status_code == 200
    skipped = {item["rule_code"] for item in result.json()["skipped_rules"]}
    assert created.json()["rule_code"] in skipped
    assert result.json()["success"] is True


def test_valid_sample_has_no_demo_violations(client: TestClient, sample_csv_bytes: bytes) -> None:
    extras = [
        item
        for item in client.get("/api/validation/rules").json()
        if item.get("enabled") and not item.get("is_sample")
    ]
    for item in extras:
        client.patch(f"/api/validation/rules/{item['id']}/disable")
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", sample_csv_bytes, "text/csv")},
    )
    batch_id = ingest.json()["batch_id"]
    try:
        result = client.post(f"/api/validation/rules/run/{batch_id}").json()
        detail = client.get(f"/api/validation/runs/{result['validation_run_id']}").json()
    finally:
        for item in extras:
            client.patch(f"/api/validation/rules/{item['id']}/enable")
    assert result["success"] is True
    assert result["records_checked"] == 4
    assert result["violations"] == 0
    assert detail["items"] == []


def test_evaluate_frame_range_and_referential() -> None:
    frame = ingest_csv_bytes((SAMPLES / "survey_invalid.csv").read_bytes()).frame
    db = SessionLocal()
    try:
        rules = db.scalars(
            select(ValidationRule).where(
                ValidationRule.enabled.is_(True),
                ValidationRule.is_sample.is_(True),
            )
        ).all()
        lookup = load_reference_lookup(db)
        rows, skipped = evaluate_frame(frame, list(rules), lookup)
        codes = {row["rule_code"] for row in rows}
        assert "CLUSTER_IN_REFERENCE" in codes
        assert all(item["reason"] == "missing field" for item in skipped)
    finally:
        db.close()


def test_nonexistent_batch(client: TestClient) -> None:
    response = client.post("/api/validation/rules/run/BATCH_NOPE")
    assert response.status_code == 404


def test_unknown_reference_set_is_skipped(client: TestClient) -> None:
    created = client.post(
        "/api/validation/rules",
        json={
            "rule_code": f"UNK_REF_{uuid4().hex[:8]}",
            "name": "Unknown reference",
            "field": "cluster_id",
            "operator": "in_reference",
            "value": "does_not_exist",
            "severity": "LOW",
        },
    )
    assert created.status_code == 200
    batch_id = _ingest_invalid(client)
    result = client.post(f"/api/validation/rules/run/{batch_id}")
    assert result.status_code == 200
    skipped = {item["rule_code"]: item["reason"] for item in result.json()["skipped_rules"]}
    assert created.json()["rule_code"] in skipped
    assert skipped[created.json()["rule_code"]] == "unknown reference set"


def test_survey_rules_are_isolated(client: TestClient) -> None:
    batch_id = _ingest_invalid(client)
    db = SessionLocal()
    try:
        batch = db.scalars(select(Batch).where(Batch.batch_id == batch_id)).first()
        assert batch is not None
        batch.survey_code = "SURVEY_A"
        db.commit()
    finally:
        db.close()

    rule_a = client.post(
        "/api/validation/rules",
        json={
            "rule_code": f"SURVEY_A_ONLY_{uuid4().hex[:8]}",
            "survey_code": "SURVEY_A",
            "name": "Survey A age floor",
            "field": "age",
            "operator": "less_than",
            "value": 0,
            "severity": "LOW",
        },
    )
    rule_b = client.post(
        "/api/validation/rules",
        json={
            "rule_code": f"SURVEY_B_ONLY_{uuid4().hex[:8]}",
            "survey_code": "SURVEY_B",
            "name": "Survey B age floor",
            "field": "age",
            "operator": "less_than",
            "value": 0,
            "severity": "LOW",
        },
    )
    assert rule_a.status_code == 200
    assert rule_b.status_code == 200
    code_a = rule_a.json()["rule_code"]
    code_b = rule_b.json()["rule_code"]

    result = client.post(f"/api/validation/rules/run/{batch_id}")
    assert result.status_code == 200
    body = result.json()
    assert body["success"] is True
    detail = client.get(f"/api/validation/runs/{body['validation_run_id']}").json()
    codes = {item["rule_code"] for item in detail["items"]}
    skipped = {item["rule_code"] for item in body["skipped_rules"]}
    assert code_a in codes
    assert code_b not in codes
    assert code_b not in skipped
    assert all(
        item["rule_code"].startswith("SURVEY_A_ONLY_") for item in detail["items"]
    )


def test_required_blank_values_are_violations() -> None:
    frame = pd.DataFrame({"cluster_id": [None, "", "   ", "C01"]})
    result = violation_mask(
        frame,
        Predicate(field="cluster_id", operator="is_not_blank"),
        when=None,
    )
    assert result.skipped is None
    assert result.mask.tolist() == [True, True, True, False]


def test_household_and_unemployed_conditional_rules() -> None:
    frame = pd.DataFrame(
        {
            "respondent_id": ["A", "B", "C"],
            "age": [30, 31, 32],
            "working_hours": [40, 40, 0],
            "income": [1000, 1000, 1000],
            "employment_status": ["employed", "unemployed", "unemployed"],
            "household_size": [0, 2, 3],
            "cluster_id": ["C01", "C01", "C01"],
            "district_code": ["1101", "1101", "1101"],
            "enumerator_id": ["E12", "E12", "E12"],
        }
    )
    db = SessionLocal()
    try:
        rules = list(
            db.scalars(
                select(ValidationRule).where(
                    ValidationRule.enabled.is_(True),
                    ValidationRule.is_sample.is_(True),
                )
            ).all()
        )
        lookup = load_reference_lookup(db)
        rows, skipped = evaluate_frame(frame, rules, lookup)
    finally:
        db.close()
    codes = {(row["record_id"], row["rule_code"]) for row in rows}
    assert ("A", "HOUSEHOLD_SIZE_MIN") in codes
    assert ("B", "UNEMPLOYED_ZERO_HOURS") in codes
    assert ("C", "UNEMPLOYED_ZERO_HOURS") not in codes
    assert skipped == []


def test_evaluate_frame_links_respondentid_column() -> None:
    frame = pd.DataFrame(
        {
            "respondentid": ["R1"],
            "age": [-5],
            "enumerator_id": ["E1"],
            "cluster_id": ["C1"],
            "district_code": ["D1"],
        }
    )
    db = SessionLocal()
    try:
        rules = list(
            db.scalars(
                select(ValidationRule).where(
                    ValidationRule.enabled.is_(True),
                    ValidationRule.rule_code == "AGE_MIN",
                )
            ).all()
        )
        lookup = load_reference_lookup(db)
        rows, skipped = evaluate_frame(frame, rules, lookup)
    finally:
        db.close()
    assert skipped == []
    assert len(rows) == 1
    assert rows[0]["record_id"] == "R1"
    assert rows[0]["rule_code"] == "AGE_MIN"
