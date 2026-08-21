import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.ai.errors import AIUnavailableError
from app.db import SessionLocal
from app.models import UnifiedRiskAssessment
from app.modules.sirl.schemas import SirlContext
from app.modules.validation.explanation.schemas import ExplanationBatchResponse, ExplanationRunRequest
from app.modules.validation.explanation.selector import select_explanation_context
from app.modules.validation.explanation.service import filter_assessments
from app.modules.pipeline.orchestrator import explanation_stage_status
from tests.test_validation_explanation import (
    VALID_EXPLANATION,
    FakeProvider,
    _disable_extra_rules,
    _latest_assessment,
    _prepare_fused_batch,
)


def test_batch_limit_and_filters(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client, "survey_quality_40.csv")
        limited = client.post(
            f"/api/validation/explanations/run/{batch_id}",
            json={"min_risk_score": 0, "limit": 2},
        )
        assert limited.status_code == 200
        body = limited.json()
        assert body["records_explained"] == 2
        assert body["limit"] == 2
        assert len(body["items"]) == 2
        assert len(fake.users) == 2

        high = client.post(
            f"/api/validation/explanations/run/{batch_id}",
            json={"severity": "HIGH", "limit": 20},
        )
        assert high.status_code == 200
        for item in high.json()["items"]:
            assert item["risk_assessment"]["severity"] == "HIGH"

        threshold = client.post(
            f"/api/validation/explanations/run/{batch_id}",
            json={"min_risk_score": 70, "limit": 20},
        )
        assert threshold.status_code == 200
        for item in threshold.json()["items"]:
            assert item["risk_assessment"]["risk_score"] >= 70
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


class _Assessment:
    def __init__(self, record_id: str, severity: str, risk_score: float) -> None:
        self.record_id = record_id
        self.severity = severity
        self.risk_score = risk_score


def test_filter_assessments_default_excludes_low() -> None:
    rows = [
        _Assessment("L1", "LOW", 12.0),
        _Assessment("M1", "MEDIUM", 40.0),
        _Assessment("H1", "HIGH", 80.0),
        _Assessment("C1", "CRITICAL", 91.0),
    ]
    selected, limit, skipped = filter_assessments(rows, ExplanationRunRequest(limit=20), 20)
    assert limit == 20
    assert skipped == 0
    assert [row.record_id for row in selected] == ["C1", "H1"]
    assert all(row.severity in {"HIGH", "CRITICAL"} for row in selected)


def test_filter_assessments_zero_high_critical_selects_none() -> None:
    rows = [_Assessment("L1", "LOW", 8.0), _Assessment("L2", "LOW", 11.0)]
    selected, _limit, skipped = filter_assessments(rows, ExplanationRunRequest(limit=20), 20)
    assert selected == []
    assert skipped == 0


def test_explanation_stage_status_never_processing() -> None:
    empty = ExplanationBatchResponse(success=True, batch_id="b", fusion_run_id=1, records_explained=0)
    assert explanation_stage_status(empty) == ("COMPLETED", False)
    failed = ExplanationBatchResponse(
        success=True, batch_id="b", fusion_run_id=1, records_explained=3, available=0, unavailable=3
    )
    assert explanation_stage_status(failed) == ("UNAVAILABLE", True)
    ok = ExplanationBatchResponse(
        success=True, batch_id="b", fusion_run_id=1, records_explained=2, available=1, unavailable=1
    )
    assert explanation_stage_status(ok) == ("COMPLETED", False)


def test_default_batch_prioritizes_high_critical(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        response = client.post(f"/api/validation/explanations/run/{batch_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["limit"] == 20
        for item in body["items"]:
            assert item["risk_assessment"]["severity"] in {"HIGH", "CRITICAL"}
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_explanation_cache_and_invalidation(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        assessment = _latest_assessment(batch_id)
        first = client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
        second = client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["explanation"]["status"] == "available"
        assert len(fake.users) == 1
        db = SessionLocal()
        try:
            row = db.scalars(
                select(UnifiedRiskAssessment).where(
                    UnifiedRiskAssessment.batch_id == batch_id,
                    UnifiedRiskAssessment.record_id == assessment.record_id,
                )
            ).first()
            assert row is not None
            row.risk_score = min(100.0, float(row.risk_score) + 1.0)
            db.commit()
        finally:
            db.close()
        third = client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
        assert third.status_code == 200
        assert len(fake.users) == 2
        assert third.json()["risk_assessment"]["risk_score"] == first.json()["risk_assessment"]["risk_score"] + 1
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_failures_are_not_cached(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider(payload={"summary": "oops"})
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        assessment = _latest_assessment(batch_id)
        client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
        client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
        assert len(fake.users) == 2
        fake.payload = VALID_EXPLANATION
        fake.error = None
        retry = client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
        assert retry.status_code == 200
        assert retry.json()["explanation"]["status"] == "available"
        assert len(fake.users) == 3
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_sirl_available_and_unavailable(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    try:
        batch_id = _prepare_fused_batch(client)
        db = SessionLocal()
        try:
            assessment = db.scalars(
                select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)
            ).first()
            missing = select_explanation_context(db, assessment, max_bytes=16384)
            assert missing["sirl_context"]["available"] is False
            assert missing["instructions"]["sirl_context_available"] is False
        finally:
            db.close()

        fake_sirl = SirlContext(
            batch_id=batch_id,
            dataset_context={"record_count": 40, "numeric_measures": ["working_hours"]},
            variable_context={
                "working_hours": {
                    "kind": "numeric",
                    "mean": 40.0,
                    "standard_deviation": 5.0,
                    "missing_rate": 0.0,
                }
            },
            historical_context={"historical_context_available": False},
        )
        monkeypatch.setattr(
            "app.modules.validation.explanation.selector.load_context",
            lambda _db, _batch_id: fake_sirl,
        )
        db = SessionLocal()
        try:
            assessment = db.scalars(
                select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)
            ).first()
            present = select_explanation_context(db, assessment, max_bytes=16384)
            assert present["sirl_context"]["available"] is True
            assert present["sirl_context"]["record_count"] == 40
            assert present["instructions"]["sirl_context_available"] is True
        finally:
            db.close()
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_grounded_response_and_invalid_ai_payload(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider(
        payload={
            **VALID_EXPLANATION,
            "risk_score": 1,
            "severity": "LOW",
            "evidence_explanations": [
                {
                    "source": "invented",
                    "finding": "Fabricated violation",
                    "severity": "CRITICAL",
                }
            ],
        }
    )
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        assessment = _latest_assessment(batch_id)
        original = (assessment.risk_score, assessment.severity)
        response = client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["explanation"]["status"] == "unavailable"
        assert body["explanation"]["reason"] == "invalid_response"
        assert body["risk_assessment"]["risk_score"] == original[0]
        assert body["risk_assessment"]["severity"] == original[1]
        user = json.loads(fake.users[0])
        assert user["instructions"]["risk_score_is_authoritative"] is True
        assert user["instructions"]["do_not_invent_evidence"] is True
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_force_regenerates_without_changing_default_cache(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        assessment = _latest_assessment(batch_id)
        path = f"/api/validation/explanations/{batch_id}/{assessment.record_id}"
        first = client.post(path)
        second = client.post(path)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["explanation"]["status"] == "available"
        assert second.json()["explanation"]["primary_reason"] == first.json()["explanation"]["primary_reason"]
        assert len(fake.users) == 1
        fake.payload = {**VALID_EXPLANATION, "primary_reason": "Forced supervisor-facing reason."}
        forced = client.post(path, params={"force": True})
        assert forced.status_code == 200
        assert len(fake.users) == 2
        assert forced.json()["explanation"]["status"] == "available"
        assert forced.json()["explanation"]["primary_reason"] == "Forced supervisor-facing reason."
        assert forced.json()["explanation"]["updated_at"] != first.json()["explanation"]["updated_at"]
        stored = client.get(path)
        assert stored.status_code == 200
        assert stored.json()["explanation"]["primary_reason"] == "Forced supervisor-facing reason."
        omitted = client.post(path)
        assert omitted.status_code == 200
        assert len(fake.users) == 2
        assert omitted.json()["explanation"]["primary_reason"] == "Forced supervisor-facing reason."
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_force_failure_preserves_previous_available_explanation(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        assessment = _latest_assessment(batch_id)
        path = f"/api/validation/explanations/{batch_id}/{assessment.record_id}"
        first = client.post(path)
        assert first.status_code == 200
        original = first.json()["explanation"]["primary_reason"]
        fake.error = AIUnavailableError("invalid_response", "AI request failed")
        forced = client.post(path, params={"force": True})
        assert forced.status_code == 200
        assert len(fake.users) == 2
        assert forced.json()["explanation"]["status"] == "unavailable"
        assert forced.json()["explanation"]["reason"] == "invalid_response"
        stored = client.get(path)
        assert stored.status_code == 200
        assert stored.json()["explanation"]["status"] == "available"
        assert stored.json()["explanation"]["primary_reason"] == original
        assert stored.json()["explanation"]["primary_reason"]
        assert stored.json()["explanation"]["evidence_explanations"]
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")
