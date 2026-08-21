import json

from fastapi.testclient import TestClient

from app.db import init_db
from app.modules.evaluation.synthetic import evaluate_demo_dataset, load_ground_truth
from app.modules.validation.seed import SAMPLE_RULES
from tests.test_validation_explanation import FakeProvider, VALID_EXPLANATION


def test_sample_rules_are_survey_quality_constraints() -> None:
    by_code = {item.rule_code: item for item in SAMPLE_RULES}
    assert by_code["AGE_MIN"].value == 0
    assert by_code["AGE_MAX"].value == 100
    assert by_code["WORKING_HOURS_MIN"].value == 0
    assert by_code["WORKING_HOURS_MAX"].value == 168
    assert by_code["INCOME_NON_NEGATIVE"].value == 0
    assert by_code["HOUSEHOLD_SIZE_MIN"].value == 1
    assert by_code["UNEMPLOYED_ZERO_HOURS"].when is not None
    assert by_code["UNEMPLOYED_ZERO_HOURS"].when.value == "unemployed"
    assert not any(item.operator == "equals" and item.field == "age" for item in SAMPLE_RULES)


def test_seed_disables_leftover_age_equals_rule(client: TestClient) -> None:
    created = client.post(
        "/api/validation/rules",
        json={
            "rule_code": "TEST_AGE_EQ_deadbeef",
            "name": "Age equals 34",
            "field": "age",
            "operator": "equals",
            "value": 34,
            "severity": "LOW",
        },
    )
    assert created.status_code == 200
    init_db()
    listed = {item["rule_code"]: item for item in client.get("/api/validation/rules").json()}
    assert listed["TEST_AGE_EQ_deadbeef"]["enabled"] is False
    assert listed["AGE_MIN"]["value"] == 0
    assert listed["HOUSEHOLD_SIZE_MIN"]["enabled"] is True


def test_controlled_demo_evaluation(client: TestClient, monkeypatch) -> None:
    fake = FakeProvider(payload=VALID_EXPLANATION)
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    report = evaluate_demo_dataset(client, fake_provider=fake)
    truth = load_ground_truth()
    assert report["intentionally_anomalous"] == 11
    assert report["intentionally_clean"] == 29
    assert report["pipeline_status"] in {"COMPLETED", "PARTIAL"}
    assert report["pipeline_status"] != "RUNNING"
    assert set(report["explained_ids"]) <= set(report["detected_ids"])
    assert report["concurrency_cap"] <= 8
    for record_id, item in truth.items():
        if item.get("expect_rule"):
            assert record_id in report["rules_ids"]
    assert "M006" not in report["rules_ids"]
    assert "M008" not in report["rules_ids"]
    assert report["rule_metrics"]["false_positives"] == 0
    assert report["rule_metrics"]["recall"] == 1.0
    dumped = json.dumps(report)
    assert "api_key" not in dumped
    assert "sk-" not in dumped


def test_prompt_distinguishes_invalid_from_unusual() -> None:
    from app.modules.validation.explanation.prompts import SYSTEM_PROMPT

    text = SYSTEM_PROMPT.lower()
    assert "review signal" in text
    assert "not proof" in text
    assert "why the record was flagged" in text
