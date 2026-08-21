from fastapi.testclient import TestClient

from app.modules.ingestion.csv_ingest import ingest_csv_bytes
from app.modules.ingestion.esigma_client import MockESigmaClient
from app.modules.ingestion.service import ingest_esigma_payload
from tests.conftest import SAMPLES


def test_csv_ingestion_success(client: TestClient, sample_csv_bytes: bytes) -> None:
    response = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", sample_csv_bytes, "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["source"] == "csv"
    assert body["rows"] == 4
    assert body["schema_version"] == "v1"
    assert "batch_id" in body
    assert body["columns"] == sorted(body["columns"])
    assert body["storage"] == "parquet"
    assert body["parquet_path"].endswith(".parquet")


def test_csv_malformed_input(client: TestClient) -> None:
    response = client.post(
        "/api/ingest/csv",
        files={"file": ("bad.csv", b'"unterminated,quote\n1,2', "text/csv")},
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_csv_empty_input(client: TestClient) -> None:
    response = client.post(
        "/api/ingest/csv",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert response.status_code == 400


def test_esigma_mock_mode_success(client: TestClient) -> None:
    response = client.post("/api/ingest/esigma")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["source"] == "esigma"
    assert body["rows"] == 4
    assert body["schema_version"] == "v1"
    assert body["storage"] == "parquet"


def test_csv_and_esigma_endpoints_same_normalized_metadata(
    client: TestClient, sample_csv_bytes: bytes
) -> None:
    csv_body = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", sample_csv_bytes, "text/csv")},
    ).json()
    esigma_body = client.post("/api/ingest/esigma").json()

    assert csv_body["rows"] == esigma_body["rows"]
    assert csv_body["columns"] == esigma_body["columns"]
    assert csv_body["dtypes"] == esigma_body["dtypes"]
    assert csv_body["schema_version"] == esigma_body["schema_version"]

    csv_frame = ingest_csv_bytes(sample_csv_bytes).frame
    json_frame = ingest_esigma_payload(
        MockESigmaClient(SAMPLES / "esigma_sample.json").fetch()
    ).frame
    assert csv_frame.equals(json_frame)
