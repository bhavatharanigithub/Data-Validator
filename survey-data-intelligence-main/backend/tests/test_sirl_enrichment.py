import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Batch, BatchStatus, SirlAiEnrichment
from app.modules.ai.errors import AIUnavailableError
from app.modules.ingestion.csv_ingest import ingest_csv_bytes
from app.modules.sirl.context import bundle_to_context
from app.modules.sirl.profiler import profile_frame
from app.modules.sirl.selector import ContextSelector
from tests.conftest import SAMPLES


VALID_ENRICHMENT = {
    "contextual_insights": ["Enumerator E12 has higher missingness than E15."],
    "important_relationships": ["Cluster C01 sits in district 1101."],
    "potential_data_quality_concerns": ["Age is missing for one of four records."],
    "context_summary": "Small PLFS-like sample with mixed employment and some missing income.",
    "confidence": 0.64,
}


class FakeProvider:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self.model = "mock-model"
        self.payload = payload or VALID_ENRICHMENT
        self.error = error
        self.users: list[str] = []

    def complete_json(self, *, system: str, user: str) -> dict:
        self.users.append(user)
        if self.error:
            raise self.error
        return self.payload


def _ingest(client: TestClient, sample_csv_bytes: bytes) -> str:
    response = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", sample_csv_bytes, "text/csv")},
    )
    assert response.status_code == 200
    return response.json()["batch_id"]


def test_selector_omits_raw_values_and_respects_size() -> None:
    frame = ingest_csv_bytes((SAMPLES / "survey_sample.csv").read_bytes()).frame
    context = bundle_to_context("BATCH_SELECT", profile_frame(frame))
    selected = ContextSelector(max_bytes=4096).select(context)
    encoded = json.dumps(selected)
    assert '"values":' not in encoded
    assert "parquet" not in encoded.lower()
    assert len(encoded.encode("utf-8")) <= 4096
    assert selected["important_variables"]
    names = [item["name"] for item in selected["important_variables"]]
    assert names[0] in {"notes", "age", "income"}


def test_profile_without_ai_config_stays_profiled(
    client: TestClient, sample_csv_bytes: bytes
) -> None:
    batch_id = _ingest(client, sample_csv_bytes)
    response = client.post(f"/api/sirl/profile/{batch_id}")
    assert response.status_code == 200
    assert response.json()["status"] == BatchStatus.PROFILED
    assert response.json()["ai_enrichment_status"] == "unavailable"
    assert response.json()["ai_enrichment_reason"] == "not_configured"
    profile = client.get(f"/api/sirl/profile/{batch_id}").json()
    assert profile["ai_enrichment"]["status"] == "unavailable"
    assert profile["ai_enrichment"]["enriched"] is False
    assert profile["dataset_context"]["record_count"] == 4


def test_enrichment_success_with_mock_provider(
    client: TestClient, sample_csv_bytes: bytes, monkeypatch
) -> None:
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.sirl.enrichment.build_ai_provider", lambda *args, **kwargs: fake
    )
    batch_id = _ingest(client, sample_csv_bytes)
    client.post(f"/api/sirl/profile/{batch_id}")
    response = client.post(f"/api/sirl/enrich/{batch_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["enriched"] is True
    assert body["context_summary"]
    assert fake.users
    assert '"values":' not in fake.users[0]
    profile = client.get(f"/api/sirl/profile/{batch_id}").json()
    assert profile["ai_enrichment"]["context_summary"] == VALID_ENRICHMENT["context_summary"]
    db = SessionLocal()
    try:
        rows = db.scalars(select(SirlAiEnrichment).where(SirlAiEnrichment.batch_id == batch_id)).all()
        assert len(rows) == 1
    finally:
        db.close()


def test_invalid_ai_shape_is_unavailable(
    client: TestClient, sample_csv_bytes: bytes, monkeypatch
) -> None:
    fake = FakeProvider(payload={"summary": "oops"})
    monkeypatch.setattr(
        "app.modules.sirl.enrichment.build_ai_provider", lambda *args, **kwargs: fake
    )
    batch_id = _ingest(client, sample_csv_bytes)
    client.post(f"/api/sirl/profile/{batch_id}")
    response = client.post(f"/api/sirl/enrich/{batch_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["reason"] == "invalid_response"
    batch = SessionLocal().scalars(select(Batch).where(Batch.batch_id == batch_id)).one()
    assert batch.status == BatchStatus.PROFILED


def test_timeout_does_not_fail_profile(
    client: TestClient, sample_csv_bytes: bytes, monkeypatch
) -> None:
    fake = FakeProvider(error=AIUnavailableError("timeout", "AI request timed out"))
    monkeypatch.setattr(
        "app.modules.sirl.enrichment.build_ai_provider", lambda *args, **kwargs: fake
    )
    batch_id = _ingest(client, sample_csv_bytes)
    profiled = client.post(f"/api/sirl/profile/{batch_id}")
    assert profiled.json()["status"] == BatchStatus.PROFILED
    assert profiled.json()["ai_enrichment_status"] == "unavailable"
    assert profiled.json()["ai_enrichment_reason"] == "timeout"


def test_rate_limit_reason(client: TestClient, sample_csv_bytes: bytes, monkeypatch) -> None:
    fake = FakeProvider(error=AIUnavailableError("rate_limit", "AI rate limit exceeded"))
    monkeypatch.setattr(
        "app.modules.sirl.enrichment.build_ai_provider", lambda *args, **kwargs: fake
    )
    batch_id = _ingest(client, sample_csv_bytes)
    client.post(f"/api/sirl/profile/{batch_id}")
    response = client.post(f"/api/sirl/enrich/{batch_id}")
    assert response.json()["reason"] == "rate_limit"


def test_rerun_profile_does_not_duplicate_enrichment(
    client: TestClient, sample_csv_bytes: bytes
) -> None:
    batch_id = _ingest(client, sample_csv_bytes)
    client.post(f"/api/sirl/profile/{batch_id}")
    client.post(f"/api/sirl/profile/{batch_id}")
    db = SessionLocal()
    try:
        rows = db.scalars(select(SirlAiEnrichment).where(SirlAiEnrichment.batch_id == batch_id)).all()
        assert len(rows) == 1
    finally:
        db.close()


def test_enrich_upserts_same_row(
    client: TestClient, sample_csv_bytes: bytes, monkeypatch
) -> None:
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.modules.sirl.enrichment.build_ai_provider", lambda *args, **kwargs: fake
    )
    batch_id = _ingest(client, sample_csv_bytes)
    client.post(f"/api/sirl/profile/{batch_id}")
    client.post(f"/api/sirl/enrich/{batch_id}")
    client.post(f"/api/sirl/enrich/{batch_id}")
    db = SessionLocal()
    try:
        rows = db.scalars(select(SirlAiEnrichment).where(SirlAiEnrichment.batch_id == batch_id)).all()
        assert len(rows) == 1
        assert rows[0].status == "available"
    finally:
        db.close()
