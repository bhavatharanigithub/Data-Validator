from datetime import UTC, datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import PipelineRun
from app.modules.pipeline.jobs import fail_stalled_pending_runs, start_workers, stop_workers
from app.modules.pipeline.recovery import recover_abandoned_runs
from app.modules.validation.intelligence.types import DetectorOutcome
from tests.conftest import SAMPLES

DEMO = SAMPLES / "survey_intelligence_demo.csv"


def _wait_pipeline(client: TestClient, batch_id: str) -> dict:
    response = client.get(f"/api/pipeline/batch/{batch_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"COMPLETED", "PARTIAL", "FAILED", "RUNNING", "PENDING"}
    return body


def test_ingest_auto_orchestrates_demo_csv(client: TestClient) -> None:
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_intelligence_demo.csv", DEMO.read_bytes(), "text/csv")},
    )
    assert ingest.status_code == 200, ingest.text
    body = ingest.json()
    batch_id = body["batch_id"]
    assert "pipeline_run_id" in body
    pipeline = _wait_pipeline(client, batch_id)
    assert pipeline["status"] in {"COMPLETED", "PARTIAL"}
    assert pipeline["status"] != "RUNNING"
    assert pipeline["is_active"] is True
    by_stage = {item["stage"]: item for item in pipeline["stages"]}
    for name in ("SIRL", "RULES", "STATISTICS", "INTELLIGENCE", "ML", "FUSION"):
        assert by_stage[name]["status"] == "COMPLETED", name
    assert by_stage["EXPLANATION"]["status"] in {"COMPLETED", "UNAVAILABLE", "SKIPPED"}
    overview = client.get("/api/dashboard/overview", params={"batch_id": batch_id}).json()
    assert overview["available"] is True
    assert overview["active_pipeline_run_id"] == pipeline["pipeline_run_id"]
    anomalies = client.get(
        "/api/dashboard/anomalies",
        params={"batch_id": batch_id, "classification_scope": "all", "page_size": 100},
    ).json()
    assert anomalies["available"] is True
    assert anomalies["total"] >= 1


def test_duplicate_upload_reuses_in_flight_or_completed(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.ingest_reuse_completed", True)
    content = DEMO.read_bytes()
    first = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_intelligence_demo.csv", content, "text/csv")},
    ).json()
    second = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_intelligence_demo.csv", content, "text/csv")},
    ).json()
    assert second["reused"] is True
    assert second["batch_id"] == first["batch_id"]
    assert second["pipeline_run_id"] == first["pipeline_run_id"]
    db = SessionLocal()
    try:
        runs = list(db.scalars(select(PipelineRun).where(PipelineRun.batch_id == first["batch_id"])).all())
        running = [run for run in runs if run.status in {"PENDING", "RUNNING"}]
        assert len(running) <= 1
    finally:
        db.close()


def test_rerun_keeps_history_and_activates_new_run(client: TestClient) -> None:
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_intelligence_demo.csv", DEMO.read_bytes(), "text/csv")},
    ).json()
    batch_id = ingest["batch_id"]
    first = client.get(f"/api/pipeline/batch/{batch_id}").json()
    assert first["status"] in {"COMPLETED", "PARTIAL"}
    first_id = first["pipeline_run_id"]
    second = client.post(f"/api/pipeline/run/{batch_id}", json={"rerun": True}).json()
    assert second["pipeline_run_id"] != first_id
    assert second["status"] in {"COMPLETED", "PARTIAL"}
    assert second["is_active"] is True
    history = client.get(f"/api/pipeline/{first_id}").json()
    assert history["pipeline_run_id"] == first_id
    assert history["is_active"] is False
    overview = client.get("/api/dashboard/overview", params={"batch_id": batch_id}).json()
    assert overview["active_pipeline_run_id"] == second["pipeline_run_id"]
    db = SessionLocal()
    try:
        rows = list(db.scalars(select(PipelineRun).where(PipelineRun.batch_id == batch_id)).all())
        assert len(rows) == 2
    finally:
        db.close()


def test_optional_historical_skip_continues_pipeline(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.validation.intelligence.orchestrator.evaluate_distribution_shift",
        lambda *args, **kwargs: DetectorOutcome(
            available=False, skipped=True, reason="No historical baseline available."
        ),
    )
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_intelligence_demo.csv", DEMO.read_bytes(), "text/csv")},
    )
    batch_id = ingest.json()["batch_id"]
    detail = client.get(f"/api/pipeline/batch/{batch_id}").json()
    assert detail["status"] in {"COMPLETED", "PARTIAL"}
    intel = next(item for item in detail["stages"] if item["stage"] == "INTELLIGENCE")
    assert intel["status"] in {"COMPLETED", "UNAVAILABLE"}
    skipped = (intel.get("detail") or {}).get("skipped") or []
    assert "HISTORICAL" in skipped
    fusion = next(item for item in detail["stages"] if item["stage"] == "FUSION")
    assert fusion["status"] == "COMPLETED"


def test_ai_unavailable_marks_partial_not_failed(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: None,
    )
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_intelligence_demo.csv", DEMO.read_bytes(), "text/csv")},
    )
    batch_id = ingest.json()["batch_id"]
    detail = client.get(f"/api/pipeline/batch/{batch_id}").json()
    assert detail["status"] == "PARTIAL"
    explanation = next(item for item in detail["stages"] if item["stage"] == "EXPLANATION")
    assert explanation["status"] == "UNAVAILABLE"
    for name in ("RULES", "STATISTICS", "INTELLIGENCE", "ML", "FUSION"):
        stage = next(item for item in detail["stages"] if item["stage"] == name)
        assert stage["status"] == "COMPLETED", name


def test_invalid_csv_does_not_create_successful_dashboard(client: TestClient) -> None:
    response = client.post(
        "/api/ingest/csv",
        files={"file": ("bad.csv", b'"unterminated,quote\n1,2', "text/csv")},
    )
    assert response.status_code == 400
    overview = client.get("/api/dashboard/overview").json()
    if overview.get("available"):
        assert overview.get("fusion_status") != "COMPLETED" or overview.get("batch_id")


def test_hard_sirl_failure_fails_auto_pipeline(client: TestClient, monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        from app.modules.sirl.errors import SirlError

        raise SirlError("parquet file was not found for batch", status_code=404)

    monkeypatch.setattr("app.modules.pipeline.orchestrator.profile_batch", boom)
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", (SAMPLES / "survey_sample.csv").read_bytes(), "text/csv")},
    )
    batch_id = ingest.json()["batch_id"]
    detail = client.get(f"/api/pipeline/batch/{batch_id}").json()
    assert detail["status"] == "FAILED"
    assert detail["error_stage"] == "SIRL"
    assert detail["error_message"]
    assert detail["is_active"] is False
    overview = client.get("/api/dashboard/overview", params={"batch_id": batch_id}).json()
    assert overview["available"] is False


def test_restart_recovery_does_not_leave_running(client: TestClient) -> None:
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", (SAMPLES / "survey_sample.csv").read_bytes(), "text/csv")},
    ).json()
    run_id = ingest["pipeline_run_id"]
    db = SessionLocal()
    try:
        run = db.get(PipelineRun, run_id)
        assert run is not None
        run.status = "RUNNING"
        run.is_active = False
        db.commit()
        recover_abandoned_runs(db)
        db.refresh(run)
        assert run.status == "FAILED"
        assert run.error_code == "RECOVERABLE"
        assert run.status != "RUNNING"
    finally:
        db.close()


def test_worker_queue_leaves_pending_and_completes(client: TestClient, monkeypatch) -> None:
    import time

    monkeypatch.setattr("app.modules.pipeline.jobs.use_sync_jobs", lambda: False)
    monkeypatch.setattr("app.modules.pipeline.service.use_sync_jobs", lambda: False)
    stop_workers()
    start_workers()
    try:
        ingest = client.post(
            "/api/ingest/csv",
            files={"file": ("survey_intelligence_demo.csv", DEMO.read_bytes(), "text/csv")},
        )
        assert ingest.status_code == 200, ingest.text
        body = ingest.json()
        batch_id = body["batch_id"]
        run_id = body["pipeline_run_id"]
        assert run_id is not None
        assert body["status"] in {"QUEUED", "PENDING", "RUNNING"}
        assert body["status"] != "COMPLETED"
        seen: set[str] = set()
        detail = None
        for _ in range(160):
            response = client.get(f"/api/pipeline/{run_id}")
            assert response.status_code == 200, response.text
            detail = response.json()
            seen.add(detail["status"])
            if detail["status"] in {"COMPLETED", "PARTIAL", "FAILED"}:
                break
            time.sleep(0.25)
        assert detail is not None
        assert "PENDING" in seen or "RUNNING" in seen
        assert detail["status"] != "PENDING"
        assert detail["status"] in {"COMPLETED", "PARTIAL"}
        assert detail["started_at"] is not None
        by_stage = {item["stage"]: item for item in detail["stages"]}
        for name in (
            "INGESTION",
            "PARQUET",
            "SIRL",
            "RULES",
            "STATISTICS",
            "INTELLIGENCE",
            "ML",
            "FUSION",
            "EXPLANATION",
        ):
            assert name in by_stage, name
        assert by_stage["INTELLIGENCE"]["status"] in {"COMPLETED", "UNAVAILABLE"}
        assert by_stage["FUSION"]["status"] == "COMPLETED"
        assert by_stage["EXPLANATION"]["status"] in {"COMPLETED", "UNAVAILABLE", "SKIPPED"}
        overview = client.get("/api/dashboard/overview", params={"batch_id": batch_id}).json()
        assert overview["active_pipeline_run_id"] == run_id
    finally:
        stop_workers()
        time.sleep(1.1)


def test_stalled_pending_run_is_failed_not_completed(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.pipeline_queue_stall_seconds", 5)
    db = SessionLocal()
    try:
        run = PipelineRun(
            batch_id="stall-batch",
            status="PENDING",
            metadata_json={
                "queued": True,
                "queued_at": (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
            },
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()
    marked = fail_stalled_pending_runs()
    assert marked >= 1
    db = SessionLocal()
    try:
        stalled = db.get(PipelineRun, run_id)
        assert stalled is not None
        assert stalled.status == "FAILED"
        assert stalled.error_code == "QUEUE_STALLED"
        assert stalled.status != "COMPLETED"
    finally:
        db.close()

