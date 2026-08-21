import inspect
import json
import logging
import threading

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    AiExplanation,
    MlEvidence,
    RuleViolation,
    StatisticalEvidence,
    UnifiedRiskAssessment,
)
from app.modules.ai.errors import AIUnavailableError
from app.modules.ai.provider import ChatCompletionsProvider
from app.modules.storage.parquet import ParquetStorage
from app.modules.validation.explanation.prompts import SYSTEM_PROMPT
from app.modules.validation.explanation.schemas import ExplanationPayload, normalize_model_explanation
from app.modules.validation.explanation.selector import (
    _size,
    has_usable_evidence,
    select_explanation_context,
)
from app.modules.validation.explanation import selector as selector_module
from tests.conftest import SAMPLES

VALID_EXPLANATION = {
    "primary_reason": (
        "Reported working hours of 70 are substantially above the observed baseline, "
        "producing a HIGH statistical deviation."
    ),
    "secondary_reason": (
        "The Isolation Forest model independently classified the combination of age, "
        "income, household size and working hours as anomalous."
    ),
    "summary": (
        "The record passes configured deterministic rules but is flagged because "
        "statistical and ML evidence both indicate unusual working-hour behavior."
    ),
    "what_it_means": (
        "The concern is not based on a single threshold. Statistical deviation in "
        "working hours and an independent ML anomaly score both support review."
    ),
    "key_findings": [
        "No deterministic rule violation was recorded.",
        "Statistical analysis identified a high deviation in working hours.",
        "The ML model assigned a high anomaly score.",
        "Two independent evidence sources agree that the record warrants review.",
    ],
    "evidence_explanations": [
        {
            "source": "statistics",
            "finding": "Working hours has a z-score of 4.67 against the available baseline.",
            "severity": "HIGH",
        },
        {
            "source": "ml",
            "finding": "Isolation Forest produced an anomaly score of 91.",
            "severity": "HIGH",
        },
    ],
    "recommended_action": "Review the original enumeration and verify the reported working hours.",
    "limitations": [],
    "explanation_confidence": 0.91,
}


class FakeProvider:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self.model = "mock-model"
        self.payload = payload or VALID_EXPLANATION
        self.error = error
        self.systems: list[str] = []
        self.users: list[str] = []
        self._lock = threading.Lock()

    def complete_json(self, *, system: str, user: str) -> dict:
        with self._lock:
            self.systems.append(system)
            self.users.append(user)
        if self.error:
            raise self.error
        return dict(self.payload)


def _disable_extra_rules(client: TestClient) -> list[int]:
    extras = [
        item
        for item in client.get("/api/validation/rules").json()
        if item.get("enabled") and not item.get("is_sample")
    ]
    for item in extras:
        client.patch(f"/api/validation/rules/{item['id']}/disable")
    return [item["id"] for item in extras]


def _prepare_fused_batch(client: TestClient, sample: str = "survey_ml_demo.csv") -> str:
    content = (SAMPLES / sample).read_bytes()
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": (sample, content, "text/csv")},
        params={"auto_pipeline": "false"},
    )
    assert ingest.status_code == 200
    batch_id = ingest.json()["batch_id"]
    rules = client.post(f"/api/validation/rules/run/{batch_id}")
    stats = client.post(f"/api/validation/statistics/run/{batch_id}")
    ml = client.post(f"/api/validation/ml/run/{batch_id}")
    fused = client.post(f"/api/validation/fusion/run/{batch_id}")
    assert rules.status_code == 200
    assert stats.status_code == 200
    assert ml.status_code == 200
    assert fused.status_code == 200
    assert fused.json()["records_assessed"] > 0
    return batch_id


def _latest_assessment(batch_id: str) -> UnifiedRiskAssessment:
    db = SessionLocal()
    try:
        rows = list(
            db.scalars(
                select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)
            ).all()
        )
        assert rows
        flagged = [row for row in rows if row.risk_score == max(item.risk_score for item in rows)]
        db.expunge_all()
        return flagged[0]
    finally:
        db.close()


def test_has_usable_evidence_requires_sources_or_rows() -> None:
    empty = {
        "rule_evidence": [],
        "statistical_evidence": [],
        "ml_evidence": [],
        "unified_assessment": {"available_sources": []},
    }
    assert has_usable_evidence(empty) is False
    assert has_usable_evidence({**empty, "unified_assessment": {"available_sources": ["rules"]}}) is True
    assert has_usable_evidence({**empty, "rule_evidence": [{"id": 1}]}) is True


def test_prompt_keeps_technical_evidence_out_of_supervisor_fields() -> None:
    text = SYSTEM_PROMPT.lower()
    assert "plain language" in text
    assert "do not use these terms in those supervisor-facing fields" in text
    assert "z-score" in text
    assert "isolation forest" in text
    assert "only in evidence_explanations" in text
    assert "possible causes" in text
    assert "data-entry error" in text
    assert "fraud" in text


def test_prompt_contains_source_of_truth_constraints() -> None:
    text = SYSTEM_PROMPT.lower()
    assert "source of truth" in text
    assert "authoritative" in text
    assert "must not" in text
    assert "fraud" in text
    assert "invent historical" in text
    assert "override risk_score" in text
    assert "override" in text and "severity" in text
    assert "json only" in text
    assert "review" in text
    assert "unavailable" in text
    assert "array" in text
    assert "primary_reason" in text
    assert "secondary_reason" in text
    assert "why the record was flagged" in text
    assert "plain language" in text
    assert "evidence_explanations" in text
    assert "z-score" in text
    assert "key_findings must be a json array of strings" in text
    assert "limitations must be a json array of strings" in text
    assert "return []" in text


def test_deepseek_dict_evidence_explanations_normalize() -> None:
    raw = {
        **VALID_EXPLANATION,
        "evidence_explanations": {
            "rule_evidence": "Rule R1 flagged working hours.",
            "statistical_evidence": "z-score is high versus the baseline.",
            "ml_evidence": "Isolation Forest assigned a high anomaly score.",
        },
        "risk_score": 1,
        "severity": "LOW",
    }
    normalized = normalize_model_explanation(raw)
    payload = ExplanationPayload.model_validate(
        {key: value for key, value in normalized.items() if key not in {"risk_score", "severity"}}
    )
    sources = {item.source for item in payload.evidence_explanations}
    assert sources == {"rules", "statistics", "ml"}
    assert all(item.finding for item in payload.evidence_explanations)


def test_normalize_limitations_string_list_and_null() -> None:
    as_string = normalize_model_explanation(
        {**VALID_EXPLANATION, "limitations": "No historical baseline was available."}
    )
    assert as_string["limitations"] == ["No historical baseline was available."]
    ExplanationPayload.model_validate(as_string)

    as_list = ["No historical baseline was available."]
    unchanged = normalize_model_explanation({**VALID_EXPLANATION, "limitations": as_list})
    assert unchanged["limitations"] == as_list
    ExplanationPayload.model_validate(unchanged)

    as_null = normalize_model_explanation({**VALID_EXPLANATION, "limitations": None})
    assert as_null["limitations"] == []
    ExplanationPayload.model_validate(as_null)

    as_empty = normalize_model_explanation({**VALID_EXPLANATION, "limitations": ""})
    assert as_empty["limitations"] == []
    ExplanationPayload.model_validate(as_empty)


def test_normalize_malformed_limitations_object_stays_invalid() -> None:
    raw = normalize_model_explanation(
        {**VALID_EXPLANATION, "limitations": {"historical": "missing baseline"}}
    )
    assert isinstance(raw["limitations"], dict)
    with pytest.raises(Exception):
        ExplanationPayload.model_validate(raw)


def test_normalize_deepseek_dict_evidence_and_string_limitations() -> None:
    raw = {
        **VALID_EXPLANATION,
        "key_findings": "Statistical and ML evidence both flag working hours.",
        "evidence_explanations": {
            "rule_evidence": "Rule R1 flagged working hours.",
            "statistical_evidence": "z-score is high versus the baseline.",
            "ml_evidence": "Isolation Forest assigned a high anomaly score.",
        },
        "limitations": "No historical baseline was available.",
        "risk_score": 1,
        "severity": "LOW",
        "agreement": "none",
    }
    normalized = normalize_model_explanation(raw)
    payload = ExplanationPayload.model_validate(
        {
            key: value
            for key, value in normalized.items()
            if key not in {"risk_score", "severity", "agreement"}
        }
    )
    assert payload.key_findings == ["Statistical and ML evidence both flag working hours."]
    assert payload.limitations == ["No historical baseline was available."]
    assert {item.source for item in payload.evidence_explanations} == {"rules", "statistics", "ml"}


def test_normalize_what_it_means_from_summary() -> None:
    raw = dict(VALID_EXPLANATION)
    raw.pop("what_it_means", None)
    payload = ExplanationPayload.model_validate(normalize_model_explanation(raw))
    assert payload.what_it_means == payload.summary


def test_explanation_confidence_range() -> None:
    with pytest.raises(Exception):
        ExplanationPayload.model_validate({**VALID_EXPLANATION, "explanation_confidence": 1.4})
    with pytest.raises(Exception):
        ExplanationPayload.model_validate({**VALID_EXPLANATION, "explanation_confidence": -2})
    payload = ExplanationPayload.model_validate({**VALID_EXPLANATION, "explanation_confidence": 0.5})
    assert payload.explanation_confidence == 0.5
    description = ExplanationPayload.model_fields["explanation_confidence"].description.lower()
    assert "not" in description
    assert "wrong" in description


def test_selector_context_size_bound_and_no_parquet(client: TestClient) -> None:
    extras = _disable_extra_rules(client)
    try:
        batch_id = _prepare_fused_batch(client)
        db = SessionLocal()
        try:
            assessment = db.scalars(
                select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)
            ).first()
            assert assessment is not None
            context = select_explanation_context(db, assessment, max_bytes=2048)
            assert _size(context) <= 2048
            encoded = json.dumps(context).lower()
            assert "parquet" not in encoded
            assert ".parquet" not in encoded
            source = inspect.getsource(selector_module)
            assert "ParquetStorage" not in source
            assert "read_parquet" not in source
        finally:
            db.close()
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_selector_does_not_read_parquet_at_runtime(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    try:
        batch_id = _prepare_fused_batch(client)

        def boom(*_args, **_kwargs):
            raise AssertionError("parquet accessed")

        monkeypatch.setattr(ParquetStorage, "read", boom)
        db = SessionLocal()
        try:
            assessment = db.scalars(
                select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)
            ).first()
            select_explanation_context(db, assessment, max_bytes=16384)
        finally:
            db.close()
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_selector_filters_unrelated_and_selects_correct_evidence(client: TestClient) -> None:
    extras = _disable_extra_rules(client)
    try:
        batch_id = _prepare_fused_batch(client)
        db = SessionLocal()
        try:
            assessments = list(
                db.scalars(
                    select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)
                ).all()
            )
            target = max(assessments, key=lambda row: row.risk_score)
            other_id = "M001" if target.record_id != "M001" else "M002"
            other_rule = RuleViolation(
                validation_run_id=target.validation_run_id,
                batch_id=batch_id,
                rule_id=1,
                rule_code="UNRELATED_RULE",
                record_id=other_id,
                severity="HIGH",
                field="notes",
                observed_value="secret-note-text",
                expected_condition="unrelated",
                message="unrelated other record",
            )
            other_stat = StatisticalEvidence(
                validation_run_id=target.validation_run_id,
                batch_id=batch_id,
                record_id=other_id,
                variable="unrelated_hours",
                detector="zscore",
                scope="record",
                observed_value=999,
                severity="HIGH",
                evidence_json={},
            )
            other_ml = MlEvidence(
                validation_run_id=target.validation_run_id,
                batch_id=batch_id,
                record_id=other_id,
                model_type="isolation_forest",
                model_version="unrelated",
                feature_names_json=["unrelated"],
                anomaly_score=99,
                prediction="anomaly",
                severity="HIGH",
                training_source="current",
                training_records=10,
                evidence_json={},
            )
            db.add_all([other_rule, other_stat, other_ml])
            db.commit()
            db.refresh(other_rule)
            db.refresh(other_stat)
            db.refresh(other_ml)
            refs = dict(target.evidence_refs_json or {})
            refs["rule_violation_ids"] = list(refs.get("rule_violation_ids") or []) + [other_rule.id]
            refs["statistical_evidence_ids"] = list(refs.get("statistical_evidence_ids") or []) + [
                other_stat.id
            ]
            refs["ml_evidence_ids"] = list(refs.get("ml_evidence_ids") or []) + [other_ml.id]
            target.evidence_refs_json = refs
            db.commit()
            context = select_explanation_context(db, target, max_bytes=16384)
            encoded = json.dumps(context)
            assert other_id not in encoded or context["unified_assessment"]["record_id"] == target.record_id
            assert "UNRELATED_RULE" not in encoded
            assert "unrelated_hours" not in encoded
            assert "secret-note-text" not in encoded
            own_rules = db.scalars(
                select(RuleViolation).where(
                    RuleViolation.batch_id == batch_id,
                    RuleViolation.record_id == target.record_id,
                )
            ).all()
            own_stats = db.scalars(
                select(StatisticalEvidence).where(
                    StatisticalEvidence.batch_id == batch_id,
                    StatisticalEvidence.record_id == target.record_id,
                )
            ).all()
            own_ml = db.scalars(
                select(MlEvidence).where(
                    MlEvidence.batch_id == batch_id,
                    MlEvidence.record_id == target.record_id,
                )
            ).all()
            selected_rule_ids = {item["id"] for item in context["rule_evidence"]}
            selected_stat_ids = {item["id"] for item in context["statistical_evidence"]}
            selected_ml_ids = {item["id"] for item in context["ml_evidence"]}
            for row in own_rules:
                if row.id in (target.evidence_refs_json or {}).get("rule_violation_ids", []):
                    assert row.id in selected_rule_ids
            for row in own_stats:
                if row.id in (target.evidence_refs_json or {}).get("statistical_evidence_ids", []):
                    assert row.id in selected_stat_ids
            for row in own_ml:
                if row.id in (target.evidence_refs_json or {}).get("ml_evidence_ids", []):
                    assert row.id in selected_ml_ids
            assert other_rule.id not in selected_rule_ids
            assert other_stat.id not in selected_stat_ids
            assert other_ml.id not in selected_ml_ids
        finally:
            db.close()
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_missing_evidence_is_marked_unavailable_not_negative(client: TestClient) -> None:
    extras = _disable_extra_rules(client)
    try:
        content = (SAMPLES / "survey_invalid.csv").read_bytes()
        ingest = client.post(
            "/api/ingest/csv",
            files={"file": ("survey_invalid.csv", content, "text/csv")},
            params={"auto_pipeline": "false"},
        )
        batch_id = ingest.json()["batch_id"]
        client.post(f"/api/validation/rules/run/{batch_id}")
        client.post(f"/api/validation/statistics/run/{batch_id}")
        fused = client.post(f"/api/validation/fusion/run/{batch_id}").json()
        assert "ml" in fused["missing_sources"]
        db = SessionLocal()
        try:
            assessment = db.scalars(
                select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)
            ).first()
            context = select_explanation_context(db, assessment, max_bytes=16384)
            assert "ml" in context["unified_assessment"]["missing_sources"]
            assert context["ml_evidence"] == []
            assert has_usable_evidence(context) is True
        finally:
            db.close()
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_insufficient_evidence_skips_ai(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        content = (SAMPLES / "survey_sample.csv").read_bytes()
        ingest = client.post(
            "/api/ingest/csv",
            files={"file": ("survey_sample.csv", content, "text/csv")},
            params={"auto_pipeline": "false"},
        )
        batch_id = ingest.json()["batch_id"]
        fused = client.post(f"/api/validation/fusion/run/{batch_id}").json()
        assert fused["records_assessed"] == 0
        response = client.post(f"/api/validation/explanations/run/{batch_id}")
        assert response.status_code == 409
        assert fake.users == []
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_ai_success_structured_json_and_no_override(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider(
        payload={
            **VALID_EXPLANATION,
            "risk_score": 1,
            "severity": "LOW",
            "evidence_confidence": 0,
            "agreement": "none",
        }
    )
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        db = SessionLocal()
        try:
            before = {
                (row.record_id, row.risk_score, row.severity, row.confidence, row.agreement)
                for row in db.scalars(
                    select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)
                ).all()
            }
            rule_n = len(db.scalars(select(RuleViolation).where(RuleViolation.batch_id == batch_id)).all())
            stat_n = len(
                db.scalars(select(StatisticalEvidence).where(StatisticalEvidence.batch_id == batch_id)).all()
            )
            ml_n = len(db.scalars(select(MlEvidence).where(MlEvidence.batch_id == batch_id)).all())
        finally:
            db.close()
        response = client.post(
            f"/api/validation/explanations/run/{batch_id}",
            json={"min_risk_score": 0, "limit": 40},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["engine"] == "explanation"
        assert body["available"] >= 1
        item = max(body["items"], key=lambda row: row["risk_assessment"]["risk_score"])
        assert item["explanation"]["status"] == "available"
        ExplanationPayload.model_validate(
            {
                "primary_reason": item["explanation"]["primary_reason"],
                "secondary_reason": item["explanation"]["secondary_reason"],
                "summary": item["explanation"]["summary"],
                "what_it_means": item["explanation"]["what_it_means"] or item["explanation"]["summary"],
                "key_findings": item["explanation"]["key_findings"],
                "evidence_explanations": item["explanation"]["evidence_explanations"],
                "recommended_action": item["explanation"]["recommended_action"],
                "limitations": item["explanation"]["limitations"],
                "explanation_confidence": item["explanation"]["explanation_confidence"],
            }
        )
        assert "working hours" in (item["explanation"]["primary_reason"] or "").lower()
        assert "isolation forest" in (item["explanation"]["secondary_reason"] or "").lower()
        assert 0 <= item["explanation"]["explanation_confidence"] <= 1
        assert item["risk_assessment"]["severity"] != "LOW" or item["risk_assessment"]["risk_score"] != 1
        assert item["risk_assessment"]["risk_score"] != 1
        db = SessionLocal()
        try:
            after = {
                (row.record_id, row.risk_score, row.severity, row.confidence, row.agreement)
                for row in db.scalars(
                    select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)
                ).all()
            }
            assert after == before
            assert len(db.scalars(select(RuleViolation).where(RuleViolation.batch_id == batch_id)).all()) == rule_n
            assert (
                len(db.scalars(select(StatisticalEvidence).where(StatisticalEvidence.batch_id == batch_id)).all())
                == stat_n
            )
            assert len(db.scalars(select(MlEvidence).where(MlEvidence.batch_id == batch_id)).all()) == ml_n
        finally:
            db.close()
        user = json.loads(fake.users[0])
        assert "parquet" not in json.dumps(user).lower()
        record_ids = {row["record_id"] for row in body["items"]}
        for payload in fake.users:
            parsed = json.loads(payload)
            assert parsed["unified_assessment"]["record_id"] in record_ids
        assert "source of truth" in fake.systems[0].lower()
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_openrouter_deepseek_v4_dict_evidence_is_available(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider(
        payload={
            **VALID_EXPLANATION,
            "evidence_explanations": {
                "rule_evidence": "Configured rule evidence supports review of working hours.",
                "statistical_evidence": "Statistical detector flagged working hours.",
                "ml_evidence": "ML anomaly score is elevated.",
            },
            "limitations": "No historical baseline was available.",
            "risk_score": 0,
            "severity": "LOW",
            "agreement": "disagree",
        }
    )
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        assessment = _latest_assessment(batch_id)
        original = (assessment.risk_score, assessment.severity, assessment.agreement)
        response = client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["explanation"]["status"] == "available"
        assert body["explanation"]["reason"] is None
        sources = {item["source"] for item in body["explanation"]["evidence_explanations"]}
        assert sources <= {"rules", "statistics", "ml", "historical"}
        assert body["explanation"]["limitations"] == ["No historical baseline was available."]
        assert body["risk_assessment"]["risk_score"] == original[0]
        assert body["risk_assessment"]["severity"] == original[1]
        assert body["risk_assessment"]["agreement"] == original[2]
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_malformed_limitations_object_is_invalid_response(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider(payload={**VALID_EXPLANATION, "limitations": {"historical": "missing"}})
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        assessment = _latest_assessment(batch_id)
        original = (assessment.risk_score, assessment.severity, assessment.agreement)
        response = client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["explanation"]["status"] == "unavailable"
        assert body["explanation"]["reason"] == "invalid_response"
        assert body["risk_assessment"]["risk_score"] == original[0]
        assert body["risk_assessment"]["severity"] == original[1]
        assert body["risk_assessment"]["agreement"] == original[2]
        assert "secret-token" not in json.dumps(body)
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_malformed_ai_json_is_unavailable(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider(payload={"summary": "oops"})
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        assessment = _latest_assessment(batch_id)
        response = client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["explanation"]["status"] == "unavailable"
        assert body["explanation"]["reason"] == "invalid_response"
        assert body["risk_assessment"]["risk_score"] == assessment.risk_score
        assert body["risk_assessment"]["severity"] == assessment.severity
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def _http_provider(status: int | None = None, timeout: bool = False, content: str | None = None):
    def handler(_request: httpx.Request) -> httpx.Response:
        if timeout:
            raise httpx.TimeoutException("timed out")
        if content is not None:
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        return httpx.Response(status or 500, json={"error": "fail secret-token"})

    return ChatCompletionsProvider(
        base_url="https://ai.example.test/v1",
        api_key="secret-token",
        model="mock-model",
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_timeout_auth_rate_limit_and_5xx_leave_phase6(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    cases = [
        (_http_provider(timeout=True), "timeout"),
        (_http_provider(401), "auth"),
        (_http_provider(403), "auth"),
        (_http_provider(429), "rate_limit"),
        (_http_provider(500), "provider_error"),
        (_http_provider(content="not-json"), "invalid_response"),
    ]
    try:
        batch_id = _prepare_fused_batch(client)
        assessment = _latest_assessment(batch_id)
        original = (assessment.risk_score, assessment.severity, assessment.confidence)
        for provider, reason in cases:
            monkeypatch.setattr(
                "app.modules.validation.explanation.service.build_ai_provider",
                lambda *args, _provider=provider, **kwargs: _provider,
            )
            response = client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
            assert response.status_code == 200
            body = response.json()
            assert body["explanation"]["status"] == "unavailable"
            assert body["explanation"]["reason"] == reason
            assert "secret-token" not in json.dumps(body)
            assert body["risk_assessment"]["risk_score"] == original[0]
            assert body["risk_assessment"]["severity"] == original[1]
            assert body["risk_assessment"]["evidence_confidence"] == original[2]
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_missing_api_configuration(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: None,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        assessment = _latest_assessment(batch_id)
        response = client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["explanation"]["status"] == "unavailable"
        assert body["explanation"]["reason"] == "not_configured"
        assert body["risk_assessment"]["risk_score"] == assessment.risk_score
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_no_api_key_in_logs_or_errors(caplog, client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    provider = _http_provider(401)
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: provider,
    )
    try:
        with caplog.at_level(logging.ERROR):
            batch_id = _prepare_fused_batch(client)
            assessment = _latest_assessment(batch_id)
            response = client.post(f"/api/validation/explanations/{batch_id}/{assessment.record_id}")
        assert response.status_code == 200
        assert "secret-token" not in caplog.text
        assert "secret-token" not in response.text
        err = AIUnavailableError("auth", "AI authentication failed")
        assert "secret-token" not in err.message
        assert "secret-token" not in str(err)
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_explanation_rerun_idempotency_and_get(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        first = client.post(
            f"/api/validation/explanations/run/{batch_id}",
            json={"min_risk_score": 0, "limit": 40},
        )
        second = client.post(
            f"/api/validation/explanations/run/{batch_id}",
            json={"min_risk_score": 0, "limit": 40},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["records_explained"] == second.json()["records_explained"]
        assert second.json()["cached"] == second.json()["records_explained"]
        assert len(fake.users) == first.json()["records_explained"]
        db = SessionLocal()
        try:
            rows = db.scalars(select(AiExplanation).where(AiExplanation.batch_id == batch_id)).all()
            assert len(rows) == second.json()["records_explained"]
            record_id = rows[0].record_id
        finally:
            db.close()
        fetched = client.get(f"/api/validation/explanations/{batch_id}/{record_id}")
        assert fetched.status_code == 200
        assert fetched.json()["explanation"]["status"] == "available"
        assert "risk_assessment" in fetched.json()
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")
