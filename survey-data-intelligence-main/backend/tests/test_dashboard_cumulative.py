from collections import Counter

from fastapi.testclient import TestClient

from tests.conftest import SAMPLES


def _ingest_and_pipeline(client: TestClient, filename: str = "survey_sample.csv") -> str:
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": (filename, (SAMPLES / filename).read_bytes(), "text/csv")},
    )
    assert ingest.status_code == 200, ingest.text
    batch_id = ingest.json()["batch_id"]
    run = client.post(f"/api/pipeline/run/{batch_id}")
    assert run.status_code == 200, run.text
    return batch_id


def _csv_batch_ids(text: str) -> set[str]:
    ids: set[str] = set()
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    if len(lines) < 2:
        return ids
    header = [part.strip() for part in lines[0].split(",")]
    if "batch_id" not in header:
        return ids
    index = header.index("batch_id")
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) > index and parts[index]:
            ids.add(parts[index])
    return ids


def test_cumulative_empty_without_processed_batches(client: TestClient) -> None:
    enumerators = client.get("/api/dashboard/enumerators", params={"view": "cumulative"}).json()
    assert enumerators["available"] is False
    assert enumerators["message"] == "No processed batches available for cumulative analysis."
    detectors = client.get("/api/analytics/detectors", params={"view": "cumulative"}).json()
    assert detectors["available"] is False
    assert "No processed batches" in (detectors.get("message") or "")
    report = client.get("/api/dashboard/reports/anomalies", params={"view": "cumulative"})
    assert report.status_code == 404


def test_current_and_cumulative_views_across_two_batches(client: TestClient) -> None:
    batch_a = _ingest_and_pipeline(client, "survey_sample.csv")
    batch_b = _ingest_and_pipeline(client, "survey_sample.csv")
    assert batch_a != batch_b

    current_a = client.get("/api/analytics/detectors", params={"batch_id": batch_a}).json()
    current_b = client.get("/api/analytics/detectors", params={"batch_id": batch_b}).json()
    assert current_a["view"] == "current_batch"
    assert current_a["records_processed"] == current_b["records_processed"]
    assert current_a["records_processed"] > 0

    cumulative = client.get("/api/analytics/detectors", params={"view": "cumulative"}).json()
    cumulative_with_a = client.get(
        "/api/analytics/detectors",
        params={"view": "cumulative", "batch_id": batch_a},
    ).json()
    cumulative_with_b = client.get(
        "/api/analytics/detectors",
        params={"view": "cumulative", "batch_id": batch_b},
    ).json()
    assert cumulative["view"] == "cumulative"
    assert cumulative["batch_count"] == 2
    assert cumulative["records_processed"] == current_a["records_processed"] + current_b["records_processed"]
    assert cumulative_with_a["records_processed"] == cumulative["records_processed"]
    assert cumulative_with_b["records_processed"] == cumulative["records_processed"]
    assert cumulative["confirmed_anomalies"] == current_a["confirmed_anomalies"] + current_b["confirmed_anomalies"]

    enums_a = client.get("/api/dashboard/enumerators", params={"batch_id": batch_a}).json()
    enums_b = client.get("/api/dashboard/enumerators", params={"batch_id": batch_b}).json()
    enums_all = client.get("/api/dashboard/enumerators", params={"view": "cumulative"}).json()
    enums_all_b = client.get(
        "/api/dashboard/enumerators",
        params={"view": "cumulative", "batch_id": batch_b},
    ).json()
    assert enums_a["available"] is True
    assert enums_all["available"] is True
    assert enums_all["message"] == "Cumulative — All Batches"
    assert {item["id"] for item in enums_all["items"]} == {item["id"] for item in enums_a["items"]} | {
        item["id"] for item in enums_b["items"]
    }
    records_a = sum(item["records"] for item in enums_a["items"])
    records_b = sum(item["records"] for item in enums_b["items"])
    records_all = sum(item["records"] for item in enums_all["items"])
    assert records_all == records_a + records_b
    assert sum(item["records"] for item in enums_all_b["items"]) == records_all
    merged_records = Counter()
    for row in enums_a["items"] + enums_b["items"]:
        merged_records[row["id"]] += row["records"]
    by_id = {item["id"]: item["records"] for item in enums_all["items"]}
    assert by_id == dict(merged_records)

    clusters_a = client.get("/api/dashboard/clusters", params={"batch_id": batch_a}).json()
    clusters_all = client.get("/api/dashboard/clusters", params={"view": "cumulative"}).json()
    cluster_records_a = sum(item["records"] for item in clusters_a["items"])
    cluster_records_all = sum(item["records"] for item in clusters_all["items"])
    assert cluster_records_all == cluster_records_a * 2

    districts_a = client.get("/api/dashboard/districts", params={"batch_id": batch_a}).json()
    districts_all = client.get("/api/dashboard/districts", params={"view": "cumulative"}).json()
    district_records_a = sum(item["records"] for item in districts_a["items"])
    district_records_all = sum(item["records"] for item in districts_all["items"])
    assert district_records_all == district_records_a * 2

    current_report = client.get("/api/dashboard/reports/batch", params={"batch_id": batch_a})
    assert current_report.status_code == 200
    current_ids = _csv_batch_ids(current_report.text)
    assert current_ids == {batch_a}

    cumulative_report = client.get("/api/dashboard/reports/batch", params={"view": "cumulative"})
    assert cumulative_report.status_code == 200
    assert "filename=\"batch-cumulative.csv\"" in cumulative_report.headers.get("content-disposition", "")
    assert "view=cumulative" in cumulative_report.text
    assert "batch_id=ALL" in cumulative_report.text
    assert _csv_batch_ids(cumulative_report.text) == {batch_a, batch_b}

    anomaly_report = client.get("/api/dashboard/reports/anomalies", params={"view": "cumulative"})
    assert anomaly_report.status_code == 200
    assert "view=cumulative" in anomaly_report.text
    assert "batch_id=ALL" in anomaly_report.text

    enumerator_report = client.get("/api/dashboard/reports/enumerators", params={"view": "cumulative"})
    assert enumerator_report.status_code == 200
    assert "enumerator_id" in enumerator_report.text

    temporal = client.get("/api/analytics/temporal", params={"view": "cumulative"}).json()
    assert temporal["view"] == "cumulative"
    if not temporal.get("items"):
        assert temporal.get("message") == "Not available for cumulative view"


def test_current_batch_enumerators_do_not_include_other_batch(client: TestClient) -> None:
    batch_a = _ingest_and_pipeline(client, "survey_sample.csv")
    _ingest_and_pipeline(client, "survey_intelligence_demo.csv")
    current = client.get("/api/dashboard/enumerators", params={"batch_id": batch_a}).json()
    detectors = client.get("/api/analytics/detectors", params={"batch_id": batch_a}).json()
    assert current["batch_id"] == batch_a
    assert current["view"] == "current_batch"
    assert detectors["records_processed"] > 0
    assert detectors["view"] == "current_batch"
