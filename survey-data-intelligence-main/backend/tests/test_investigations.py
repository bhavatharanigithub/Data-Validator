from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import UnifiedRiskAssessment
from tests.conftest import SAMPLES


def _ingest_and_fuse(client: TestClient) -> tuple[str, str, float]:
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", (SAMPLES / "survey_sample.csv").read_bytes(), "text/csv")},
    )
    batch_id = ingest.json()["batch_id"]
    client.post(f"/api/sirl/profile/{batch_id}")
    client.post(f"/api/validation/rules/run/{batch_id}")
    client.post(f"/api/validation/statistics/run/{batch_id}")
    client.post(f"/api/validation/ml/run/{batch_id}")
    client.post(f"/api/validation/fusion/run/{batch_id}")
    anomalies = client.get(
        "/api/dashboard/anomalies",
        params={"batch_id": batch_id, "page_size": 50, "classification_scope": "all"},
    ).json()
    item = anomalies["items"][0]
    return batch_id, item["record_id"], item["risk_score"]


def test_investigation_lifecycle_and_audit(client: TestClient) -> None:
    batch_id, record_id, risk = _ingest_and_fuse(client)
    created = client.post(
        "/api/investigations",
        json={"batch_id": batch_id, "record_id": record_id},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "OPEN"
    investigation_id = body["id"]

    review = client.patch(f"/api/investigations/{investigation_id}", json={"action": "REVIEW"})
    assert review.json()["status"] == "IN_REVIEW"

    note = client.post(f"/api/investigations/{investigation_id}/notes", json={"note": "Checking source documents."})
    assert note.status_code == 200
    assert "Checking source" in note.json()["supervisor_notes"]

    reenum = client.patch(
        f"/api/investigations/{investigation_id}",
        json={"action": "REQUEST_REENUMERATION"},
    )
    assert reenum.json()["status"] == "REQUIRES_REENUMERATION"
    assert reenum.json()["action"] == "REQUEST_REENUMERATION"

    resolved = client.patch(f"/api/investigations/{investigation_id}", json={"action": "MARK_VALID"})
    assert resolved.json()["status"] == "RESOLVED_VALID"
    assert resolved.json()["resolved_at"] is not None

    invalid = client.patch(f"/api/investigations/{investigation_id}", json={"status": "NOT_A_STATUS"})
    assert invalid.status_code == 422

    audit = client.get(f"/api/investigations/{investigation_id}/audit").json()
    actions = [row["action"] for row in audit]
    assert "CREATE" in actions
    assert "REVIEW" in actions
    assert "ADD_NOTE" in actions
    assert "REQUEST_REENUMERATION" in actions
    assert "MARK_VALID" in actions
    statuses = [row["new_status"] for row in audit]
    assert statuses[0] == "OPEN"
    assert "IN_REVIEW" in statuses

    db = SessionLocal()
    try:
        row = db.scalars(
            select(UnifiedRiskAssessment).where(
                UnifiedRiskAssessment.batch_id == batch_id,
                UnifiedRiskAssessment.record_id == record_id,
            )
        ).first()
        assert row is not None
        assert row.risk_score == risk
    finally:
        db.close()


def test_investigation_filter_and_unauthorized(client: TestClient, anon_client: TestClient) -> None:
    batch_id, record_id, _ = _ingest_and_fuse(client)
    created = client.post("/api/investigations", json={"batch_id": batch_id, "record_id": record_id}).json()
    listed = client.get("/api/investigations", params={"status": "OPEN", "batch_id": batch_id})
    assert listed.status_code == 200
    assert listed.json()["kpis"]["OPEN"] >= 1
    assert all(item["status"] == "OPEN" for item in listed.json()["items"])
    denied = anon_client.patch(f"/api/investigations/{created['id']}", json={"action": "ESCALATE"})
    assert denied.status_code == 401


def test_secrets_not_in_status_endpoints(anon_client: TestClient) -> None:
    esigma = anon_client.get("/api/esigma/status").json()
    ai = anon_client.get("/api/ai/health").json()
    for payload in (esigma, ai):
        dumped = str(payload).lower()
        assert "api_key" not in dumped
        assert "authorization" not in dumped
        assert "sk-" not in dumped
