from fastapi.testclient import TestClient

from tests.conftest import SAMPLES


def test_dashboard_empty_state(client: TestClient) -> None:
    overview = client.get("/api/dashboard/overview", params={"batch_id": "BATCH_MISSING"})
    assert overview.status_code == 200
    body = overview.json()
    assert body["available"] is False
    assert body["high_risk"] is None


def test_missing_batch_apis_do_not_500(client: TestClient) -> None:
    assert client.get("/api/batches/BATCH_MISSING").status_code == 404
    assert client.get("/api/pipeline/batch/BATCH_MISSING").status_code == 404
    anomalies = client.get("/api/dashboard/anomalies", params={"batch_id": "BATCH_MISSING"})
    assert anomalies.status_code == 200
    assert anomalies.json()["available"] is False
    assert anomalies.json()["items"] == []


def test_dashboard_overview_uses_fusion_counts(client: TestClient) -> None:
    extras = [
        item
        for item in client.get("/api/validation/rules").json()
        if item.get("enabled") and not item.get("is_sample")
    ]
    for item in extras:
        client.patch(f"/api/validation/rules/{item['id']}/disable")
    try:
        content = (SAMPLES / "survey_ml_demo.csv").read_bytes()
        ingest = client.post(
            "/api/ingest/csv",
            files={"file": ("survey_ml_demo.csv", content, "text/csv")},
        )
        batch_id = ingest.json()["batch_id"]
        client.post(f"/api/validation/rules/run/{batch_id}")
        client.post(f"/api/validation/statistics/run/{batch_id}")
        client.post(f"/api/validation/ml/run/{batch_id}")
        fused = client.post(f"/api/validation/fusion/run/{batch_id}").json()
        overview = client.get("/api/dashboard/overview", params={"batch_id": batch_id}).json()
        assert overview["available"] is True
        assert overview["confirmed_anomalies"] == fused["confirmed_anomalies"]
        assert overview["critical"] + overview["high_risk"] == fused["confirmed_anomalies"]
        pipeline = client.get(f"/api/dashboard/pipeline/{batch_id}").json()
        fusion_stage = next(stage for stage in pipeline["stages"] if stage["id"] == "fusion")
        assert fusion_stage["status"] == "COMPLETED"
        anomalies = client.get(
            "/api/dashboard/anomalies",
            params={"batch_id": batch_id, "page": 1, "page_size": 10, "severity": "HIGH"},
        ).json()
        assert anomalies["available"] is True
        for item in anomalies["items"]:
            assert item["severity"] == "HIGH"
            assert item["anomaly_status"] == "CONFIRMED"
        if anomalies["items"]:
            record_id = anomalies["items"][0]["record_id"]
            detail = client.get(f"/api/dashboard/records/{batch_id}/{record_id}").json()
            assert detail["assessment"]["risk_score"] == anomalies["items"][0]["risk_score"]
            assert "sources" in detail
        report = client.get("/api/dashboard/reports/high-risk", params={"batch_id": batch_id})
        assert report.status_code == 200
        assert "text/csv" in report.headers["content-type"]
        assert b"batch_id=" in report.content or "batch_id" in report.text
        assert "api_key" not in report.text
        esigma = client.get("/api/esigma/status").json()
        assert "api_key" not in esigma
        assert "notice" in esigma
    finally:
        for item in extras:
            client.patch(f"/api/validation/rules/{item['id']}/enable")
