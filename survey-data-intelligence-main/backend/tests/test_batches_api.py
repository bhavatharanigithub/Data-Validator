from fastapi.testclient import TestClient

from app.config import PROJECT_ROOT
from app.models import BatchStatus


def test_csv_ingestion_creates_completed_batch(
    client: TestClient, sample_csv_bytes: bytes
) -> None:
    response = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", sample_csv_bytes, "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["storage"] == "parquet"
    assert body["parquet_path"].startswith("data/processed/")
    assert body["parquet_path"].endswith(".parquet")

    parquet_file = PROJECT_ROOT / body["parquet_path"]
    assert parquet_file.is_file()

    meta = client.get(f"/api/batches/{body['batch_id']}")
    assert meta.status_code == 200
    assert meta.json()["status"] in {BatchStatus.COMPLETED, BatchStatus.PROFILED}
    assert meta.json()["records"] == 4


def test_esigma_ingestion_creates_completed_batch(client: TestClient) -> None:
    response = client.post("/api/ingest/esigma")
    assert response.status_code == 200
    body = response.json()
    assert body["storage"] == "parquet"
    parquet_file = PROJECT_ROOT / body["parquet_path"]
    assert parquet_file.is_file()

    meta = client.get(f"/api/batches/{body['batch_id']}")
    assert meta.status_code == 200
    assert meta.json()["status"] in {BatchStatus.COMPLETED, BatchStatus.PROFILED}


def test_get_batches_lists_recent(client: TestClient, sample_csv_bytes: bytes) -> None:
    created = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", sample_csv_bytes, "text/csv")},
    ).json()
    listing = client.get("/api/batches")
    assert listing.status_code == 200
    ids = [item["batch_id"] for item in listing.json()["items"]]
    assert created["batch_id"] in ids


def test_get_batch_not_found(client: TestClient) -> None:
    response = client.get("/api/batches/BATCH_DOES_NOT_EXIST")
    assert response.status_code == 404
