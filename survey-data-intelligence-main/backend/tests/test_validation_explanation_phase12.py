import json
import threading
import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings as current
from app.db import SessionLocal
from app.models import UnifiedRiskAssessment
from app.modules.validation.explanation.repository import display_status
from app.modules.validation.explanation.schemas import ExplanationRunRequest
from app.modules.validation.explanation.service import filter_assessments
from tests.test_validation_explanation import (
    VALID_EXPLANATION,
    FakeProvider,
    _disable_extra_rules,
    _latest_assessment,
    _prepare_fused_batch,
)

CLEAN_EXPLANATION = {
    **VALID_EXPLANATION,
    "primary_reason": "No configured deterministic rule violation was identified for this record.",
    "secondary_reason": "No statistical or ML detector produced an actionable anomaly for the record.",
    "summary": "The record currently shows no detected evidence requiring investigation.",
    "recommended_action": "No immediate action is indicated; retain the record for normal quality monitoring.",
    "evidence_explanations": [],
    "key_findings": [
        "No deterministic rule violation was recorded.",
        "No statistical or ML detector produced an actionable anomaly.",
    ],
}


class _CountingProvider:
    def __init__(self) -> None:
        self.model = "mock-model"
        self.current = 0
        self.max_seen = 0
        self.lock = threading.Lock()
        self.users: list[str] = []

    def complete_json(self, *, system: str, user: str) -> dict:
        with self.lock:
            self.current += 1
            self.max_seen = max(self.max_seen, self.current)
            self.users.append(user)
        time.sleep(0.05)
        with self.lock:
            self.current -= 1
        return dict(VALID_EXPLANATION)


def test_display_status_not_generated_vs_unavailable() -> None:
    assert display_status(None) == "not_generated"
    assert display_status(None, detected=False) == "not_required"


def test_scope_all_includes_low_medium_high(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client, "survey_quality_40.csv")
        response = client.post(
            f"/api/validation/explanations/run/{batch_id}",
            json={"scope": "all", "limit": 40},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == "all"
        assert body["records_explained"] >= 3
        statuses = {item["risk_assessment"].get("anomaly_status") for item in body["items"]}
        severities = {item["risk_assessment"]["severity"] for item in body["items"]}
        assert "HIGH" in severities or "CRITICAL" in severities
        assert "NORMAL" in statuses or "REVIEW" in statuses or "LOW" in severities or "MEDIUM" in severities
        for item in body["items"]:
            if (item["risk_assessment"] or {}).get("anomaly_status") == "NORMAL":
                assert item["explanation"]["status"] == "not_required"
                continue
            assert item["explanation"]["primary_reason"]
            assert item["explanation"]["secondary_reason"]
            assert item["explanation"]["status"] == "available"
            assert item["risk_assessment"]["risk_score"] != 1
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_high_medium_low_and_clean_explanations(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider(payload=CLEAN_EXPLANATION)
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        db = SessionLocal()
        try:
            rows = list(
                db.scalars(select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)).all()
            )
        finally:
            db.close()
        by_sev: dict[str, str] = {}
        for row in rows:
            from app.modules.validation.fusion.classification import should_auto_explain

            if not should_auto_explain(row):
                continue
            by_sev.setdefault(row.severity, row.record_id)
        for severity in ("HIGH", "MEDIUM", "LOW"):
            if severity not in by_sev:
                continue
            response = client.post(f"/api/validation/explanations/{batch_id}/{by_sev[severity]}")
            assert response.status_code == 200
            body = response.json()
            assert body["explanation"]["status"] == "available"
            assert body["explanation"]["primary_reason"]
            assert body["explanation"]["secondary_reason"]
            assert body["risk_assessment"]["severity"] == severity
            user = fake.users[-1].lower()
            if severity == "HIGH":
                assert "working" in user or "hours" in user or "ml" in user or "rule" in user
        anomalies = client.get(
            f"/api/dashboard/anomalies?batch_id={batch_id}&page_size=50&classification_scope=all"
        ).json()
        statuses = {item["record_id"]: item["ai_explanation_status"] for item in anomalies["items"]}
        explained = {by_sev[key] for key in by_sev if key in {"HIGH", "MEDIUM", "LOW"}}
        for record_id, status in statuses.items():
            if record_id in explained:
                assert status == "available"
            else:
                assert status in {"not_generated", "not_required"}
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_clean_context_is_not_suspicious(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider(payload=CLEAN_EXPLANATION)
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        response = client.post(
            f"/api/validation/explanations/run/{batch_id}",
            json={"scope": "all", "limit": 40},
        )
        assert response.status_code == 200
        body = response.json()
        normals = [
            item
            for item in body["items"]
            if (item.get("risk_assessment") or {}).get("anomaly_status") == "NORMAL"
        ]
        assert normals
        assert all(item["explanation"]["status"] == "not_required" for item in normals)
        reviewed = [item for item in body["items"] if item["explanation"]["status"] == "available"]
        for item in reviewed:
            assert "suspicious" not in (item["explanation"]["primary_reason"] or "").lower()
            assert item["explanation"]["primary_reason"]
            assert item["explanation"]["secondary_reason"]
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_reasons_grounded_in_supplied_evidence(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        assessment = _latest_assessment(batch_id)
        response = client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
        body = response.json()
        user = fake.users[0].lower()
        assert "rule_evidence" in user
        assert "statistical_evidence" in user
        assert "ml_evidence" in user
        assert "working hours" in body["explanation"]["primary_reason"].lower()
        assert "isolation forest" in body["explanation"]["secondary_reason"].lower()
        assert body["risk_assessment"]["risk_score"] == assessment.risk_score
        assert body["risk_assessment"]["severity"] == assessment.severity
        assert body["risk_assessment"]["agreement"] == assessment.agreement
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_bounded_concurrency(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    provider = _CountingProvider()
    original = current.ai_explanation_concurrency
    current.ai_explanation_concurrency = 3
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: provider,
    )
    try:
        batch_id = _prepare_fused_batch(client, "survey_quality_40.csv")
        response = client.post(
            f"/api/validation/explanations/run/{batch_id}",
            json={"scope": "detected", "limit": 12},
        )
        assert response.status_code == 200
        assert provider.max_seen <= 3
        assert provider.max_seen >= 1
        assert len(provider.users) >= 3
    finally:
        current.ai_explanation_concurrency = original
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_filter_scope_all_keeps_low_rows() -> None:
    class Row:
        def __init__(self, record_id: str, severity: str, risk_score: float) -> None:
            self.record_id = record_id
            self.severity = severity
            self.risk_score = risk_score
            self.batch_id = "b"

    rows = [
        Row("L1", "LOW", 8.0),
        Row("M1", "MEDIUM", 30.0),
        Row("H1", "HIGH", 70.0),
    ]
    selected, limit, skipped = filter_assessments(
        rows, ExplanationRunRequest(scope="all", limit=20), 20  # type: ignore[arg-type]
    )
    assert limit == 20
    assert skipped == 0
    assert {row.record_id for row in selected} == {"L1", "M1", "H1"}


def test_filter_scope_detected_includes_low_medium_high_not_clean() -> None:
    class Row:
        def __init__(self, record_id: str, severity: str, risk_score: float, refs: dict) -> None:
            self.record_id = record_id
            self.severity = severity
            self.risk_score = risk_score
            self.batch_id = "b"
            self.evidence_refs_json = refs

    rows = [
        Row("L1", "LOW", 8.0, {"statistical_evidence_ids": [1]}),
        Row("M1", "MEDIUM", 30.0, {"rule_violation_ids": [2], "rule_codes": ["AGE_MIN"]}),
        Row("H1", "HIGH", 70.0, {"ml_evidence_ids": [3]}),
        Row("C1", "CRITICAL", 90.0, {"statistical_evidence_ids": [4], "ml_evidence_ids": [5]}),
        Row("CLEAN", "LOW", 0.0, {}),
    ]
    selected, _limit, skipped = filter_assessments(
        rows, ExplanationRunRequest(scope="detected", limit=20), 20  # type: ignore[arg-type]
    )
    assert skipped == 0
    assert {row.record_id for row in selected} == {"L1", "M1", "H1", "C1"}


def test_pipeline_skips_clean_records(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        client.post(f"/api/pipeline/run/{batch_id}")
        for payload in fake.users:
            context = json.loads(payload)
            assert context.get("no_detected_evidence") is not True
            evidence = (
                context.get("rule_evidence")
                or context.get("statistical_evidence")
                or context.get("ml_evidence")
            )
            assert evidence
        anomalies = client.get(
            f"/api/dashboard/anomalies?batch_id={batch_id}&page_size=50&classification_scope=all"
        ).json()
        for item in anomalies["items"]:
            if item["ai_explanation_status"] == "not_required":
                assert item["severity"] in {"LOW", "NONE"}
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_demo40_rule_explanation_includes_observed_hours(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client, "survey_demo_40.csv")
        body = client.post(f"/api/validation/explanations/{batch_id}/M032").json()
        user = fake.users[-1]
        assert "190" in user
        assert body["explanation"]["primary_reason"]
        assert body["explanation"]["secondary_reason"]
        assert body["risk_assessment"]["risk_score"] is not None
        clean = client.post(f"/api/validation/explanations/{batch_id}/M001")
        assert clean.status_code in {200, 404, 409}
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")

