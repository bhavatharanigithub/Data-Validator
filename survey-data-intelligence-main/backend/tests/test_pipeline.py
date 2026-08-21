import json

from fastapi.testclient import TestClient

from sqlalchemy import select

from app.config import settings as current
from app.db import SessionLocal
from app.models import PipelineRun, UnifiedRiskAssessment
from app.modules.dashboard.service import esigma_status
from app.modules.pipeline.repository import STAGE_ORDER
from app.modules.sirl.errors import SirlError
from app.modules.validation.fusion.classification import should_auto_explain
from tests.conftest import SAMPLES
from tests.test_validation_explanation import FakeProvider, _disable_extra_rules, _prepare_fused_batch


def test_esigma_status_modes_and_no_secrets() -> None:
    mock = esigma_status()
    assert "api_key" not in mock
    assert "authorization" not in mock["notice"].lower()
    original = (current.esigma_mock_mode, current.esigma_base_url, current.esigma_api_key)
    try:
        current.esigma_mock_mode = False
        current.esigma_base_url = ""
        current.esigma_api_key = ""
        payload = esigma_status()
        assert payload["status"] == "NOT_CONFIGURED"
        current.esigma_mock_mode = True
        assert esigma_status()["status"] == "MOCK"
        current.esigma_mock_mode = False
        current.esigma_base_url = "https://esigma.example.test"
        current.esigma_api_key = "secret-token"
        configured = esigma_status(probe=False)
        assert configured["status"] == "CONFIGURED_BUT_UNVERIFIED"
        assert "secret-token" not in str(configured)
    finally:
        current.esigma_mock_mode, current.esigma_base_url, current.esigma_api_key = original


def test_pipeline_runs_stages_in_order(client: TestClient) -> None:
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", (SAMPLES / "survey_sample.csv").read_bytes(), "text/csv")},
    )
    batch_id = ingest.json()["batch_id"]
    started = client.post(f"/api/pipeline/run/{batch_id}")
    assert started.status_code == 200
    run_id = started.json()["pipeline_run_id"]
    status = client.get(f"/api/pipeline/{run_id}")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] in {"COMPLETED", "PARTIAL"}
    names = [item["stage"] for item in body["stages"]]
    assert names == STAGE_ORDER
    assert body["metadata"]["call_order"] == [
        "SIRL",
        "RULES",
        "STATISTICS",
        "INTELLIGENCE",
        "ML",
        "FUSION",
        "EXPLANATION",
    ]
    by_stage = {item["stage"]: item for item in body["stages"]}
    assert by_stage["SIRL"]["status"] == "COMPLETED"
    assert by_stage["RULES"]["status"] == "COMPLETED"
    assert by_stage["STATISTICS"]["status"] == "COMPLETED"
    assert by_stage["ML"]["status"] in {"COMPLETED", "UNAVAILABLE"}
    assert by_stage["FUSION"]["status"] == "COMPLETED"
    assert by_stage["EXPLANATION"]["status"] in {"COMPLETED", "UNAVAILABLE"}
    batch_view = client.get(f"/api/pipeline/batch/{batch_id}")
    assert batch_view.json()["pipeline_run_id"] == run_id
    assert "secret" not in str(body).lower() or "secret-token" not in str(body)


def test_duplicate_pipeline_returns_existing(client: TestClient) -> None:
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", (SAMPLES / "survey_sample.csv").read_bytes(), "text/csv")},
    )
    batch_id = ingest.json()["batch_id"]
    first = client.post(f"/api/pipeline/run/{batch_id}").json()
    second = client.post(f"/api/pipeline/run/{batch_id}").json()
    assert first["pipeline_run_id"] == second["pipeline_run_id"]
    assert second["reused"] is True
    rerun = client.post(f"/api/pipeline/run/{batch_id}", json={"rerun": True}).json()
    assert rerun["pipeline_run_id"] != first["pipeline_run_id"]
    db = SessionLocal()
    try:
        rows = db.scalars(select(PipelineRun).where(PipelineRun.batch_id == batch_id)).all()
        assert len(rows) == 2
    finally:
        db.close()


def test_ai_unavailable_does_not_fail_pipeline(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: None,
    )
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_ml_demo.csv", (SAMPLES / "survey_ml_demo.csv").read_bytes(), "text/csv")},
    )
    batch_id = ingest.json()["batch_id"]
    body = client.post(f"/api/pipeline/run/{batch_id}").json()
    detail = client.get(f"/api/pipeline/{body['pipeline_run_id']}").json()
    assert detail["status"] in {"COMPLETED", "PARTIAL"}
    explanation = next(item for item in detail["stages"] if item["stage"] == "EXPLANATION")
    assert explanation["status"] == "UNAVAILABLE"
    fusion = next(item for item in detail["stages"] if item["stage"] == "FUSION")
    assert fusion["status"] == "COMPLETED"


def test_hard_sirl_failure_stops_pipeline(client: TestClient, monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise SirlError("parquet file was not found for batch", status_code=404)

    monkeypatch.setattr("app.modules.pipeline.orchestrator.profile_batch", boom)
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", (SAMPLES / "survey_sample.csv").read_bytes(), "text/csv")},
    )
    batch_id = ingest.json()["batch_id"]
    run_id = client.post(f"/api/pipeline/run/{batch_id}").json()["pipeline_run_id"]
    detail = client.get(f"/api/pipeline/{run_id}").json()
    assert detail["status"] == "FAILED"
    assert detail["error_stage"] == "SIRL"
    names = [item["stage"] for item in detail["stages"] if item["status"] == "COMPLETED"]
    assert "RULES" not in names
    assert "FUSION" not in names


def test_pipeline_explains_all_detected_severities(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        body = client.post(f"/api/pipeline/run/{batch_id}").json()
        detail = client.get(f"/api/pipeline/{body['pipeline_run_id']}").json()
        assert detail["status"] in {"COMPLETED", "PARTIAL"}
        assert detail["status"] != "RUNNING"
        explanation = next(item for item in detail["stages"] if item["stage"] == "EXPLANATION")
        assert explanation["status"] in {"COMPLETED", "UNAVAILABLE"}
        assert explanation["status"] != "PROCESSING"
        assert fake.users
        explained_ids = {json.loads(payload)["unified_assessment"]["record_id"] for payload in fake.users}
        db = SessionLocal()
        try:
            rows = list(
                db.scalars(select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)).all()
            )
        finally:
            db.close()
        seen = set()
        for row in rows:
            if should_auto_explain(row):
                assert row.record_id in explained_ids
                seen.add(row.severity)
            else:
                assert row.record_id not in explained_ids
        assert seen & {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_pipeline_zero_high_critical_does_not_stay_running(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.filter_assessments",
        lambda rows, request, default_limit: ([], default_limit, 0),
    )
    try:
        batch_id = _prepare_fused_batch(client)
        detail = client.post(f"/api/pipeline/run/{batch_id}").json()
        body = client.get(f"/api/pipeline/{detail['pipeline_run_id']}").json()
        assert body["status"] in {"COMPLETED", "PARTIAL"}
        assert body["status"] != "RUNNING"
        explanation = next(item for item in body["stages"] if item["stage"] == "EXPLANATION")
        assert explanation["status"] == "COMPLETED"
        assert explanation["status"] != "PROCESSING"
        assert fake.users == []
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_pipeline_all_ai_failures_are_partial_not_running(client: TestClient, monkeypatch) -> None:
    extras = _disable_extra_rules(client)
    fake = FakeProvider(payload={"summary": "oops"})
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        batch_id = _prepare_fused_batch(client)
        run_id = client.post(f"/api/pipeline/run/{batch_id}").json()["pipeline_run_id"]
        detail = client.get(f"/api/pipeline/{run_id}").json()
        assert detail["status"] == "PARTIAL"
        assert detail["status"] != "RUNNING"
        explanation = next(item for item in detail["stages"] if item["stage"] == "EXPLANATION")
        assert explanation["status"] == "UNAVAILABLE"
        fusion = next(item for item in detail["stages"] if item["stage"] == "FUSION")
        assert fusion["status"] == "COMPLETED"
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_pipeline_missing_batch(client: TestClient) -> None:
    assert client.post("/api/pipeline/run/BATCH_NONE").status_code == 404
    assert client.get("/api/pipeline/batch/BATCH_NONE").status_code == 404


def test_ingest_auto_starts_pipeline(client: TestClient) -> None:
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", (SAMPLES / "survey_sample.csv").read_bytes(), "text/csv")},
    )
    body = ingest.json()
    batch_id = body["batch_id"]
    assert body.get("pipeline_run_id") is not None
    pipeline = client.get(f"/api/pipeline/batch/{batch_id}")
    assert pipeline.status_code == 200
    assert pipeline.json()["status"] in {"COMPLETED", "PARTIAL", "RUNNING", "PENDING"}


def test_mock_esigma_ingest_then_pipeline(client: TestClient) -> None:
    ingest = client.post("/api/ingest/esigma")
    assert ingest.status_code == 200
    batch_id = ingest.json()["batch_id"]
    started = client.post(f"/api/pipeline/run/{batch_id}")
    assert started.status_code == 200
    detail = client.get(f"/api/pipeline/{started.json()['pipeline_run_id']}").json()
    assert detail["status"] in {"COMPLETED", "PARTIAL"}
    by_stage = {item["stage"]: item for item in detail["stages"]}
    assert by_stage["INGESTION"]["status"] == "COMPLETED"
    assert by_stage["FUSION"]["status"] == "COMPLETED"


def test_esigma_status_http_hides_secrets(client: TestClient) -> None:
    response = client.get("/api/esigma/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"MOCK", "NOT_CONFIGURED", "CONFIGURED", "CONFIGURED_BUT_UNVERIFIED", "REACHABLE", "AUTH_FAILED", "TIMEOUT", "UNAVAILABLE"}
    dumped = str(body).lower()
    assert "api_key" not in dumped
    assert "authorization" not in dumped
    assert "bearer " not in dumped
