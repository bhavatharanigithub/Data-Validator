from fastapi.testclient import TestClient

from tests.conftest import SAMPLES


def test_intelligence_pipeline_and_summary(client: TestClient) -> None:
    ingest = client.post(
        "/api/ingest/csv",
        files={
            "file": (
                "survey_intelligence_demo.csv",
                (SAMPLES / "survey_intelligence_demo.csv").read_bytes(),
                "text/csv",
            )
        },
    )
    assert ingest.status_code == 200
    batch_id = ingest.json()["batch_id"]
    run = client.post(f"/api/pipeline/run/{batch_id}")
    assert run.status_code == 200
    summary = client.get("/api/anomalies/summary", params={"batch_id": batch_id}).json()
    assert "by_detector" in summary
    assert summary["detectors_available"]
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    detectors = client.get("/api/detectors").json()
    assert any(item["detector_id"] == "ENUMERATOR_DEVIATION" for item in detectors)
    anomalies = client.get("/api/anomalies", params={"batch_id": batch_id}).json()
    assert anomalies["available"] is True
    temporal = client.get("/api/analytics/temporal", params={"batch_id": batch_id}).json()
    assert "items" in temporal
