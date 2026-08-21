from uuid import uuid4

from datetime import UTC, datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    Batch,
    BatchStatus,
    DatasetProfile,
    EnumeratorProfile,
    RecordProfile,
    VariableProfile,
)
from app.modules.ingestion.csv_ingest import ingest_csv_bytes
from app.modules.sirl.profiler import detect_roles, profile_frame
from tests.conftest import SAMPLES


def _ingest(client: TestClient, sample_csv_bytes: bytes) -> str:
    response = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", sample_csv_bytes, "text/csv")},
    )
    assert response.status_code == 200
    return response.json()["batch_id"]


def test_sirl_profiles_completed_batch(client: TestClient, sample_csv_bytes: bytes) -> None:
    batch_id = _ingest(client, sample_csv_bytes)
    response = client.post(f"/api/sirl/profile/{batch_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["status"] == BatchStatus.PROFILED
    assert body["records"] == 4
    assert body["profiles_created"]["dataset"] is True
    assert body["profiles_created"]["variables"] == 10
    assert body["profiles_created"]["records"] == 4
    assert body["profiles_created"]["enumerators"] == 2
    assert body["profiles_created"]["clusters"] == 2
    assert body["profiles_created"]["districts"] == 2
    assert "historical_context_available" in body
    assert body["ai_enrichment_status"] in {"available", "unavailable"}


def test_sirl_persists_and_retrieves_profiles(
    client: TestClient, sample_csv_bytes: bytes
) -> None:
    batch_id = _ingest(client, sample_csv_bytes)
    client.post(f"/api/sirl/profile/{batch_id}")
    profile = client.get(f"/api/sirl/profile/{batch_id}")
    assert profile.status_code == 200
    context = profile.json()
    assert context["dataset_context"]["record_count"] == 4
    assert "age" in context["variable_context"]
    assert len(context["record_context"]) == 4
    assert "E12" in context["enumerator_context"]
    assert "C01" in context["cluster_context"]
    assert "1101" in context["district_context"]

    variables = client.get(f"/api/sirl/profile/{batch_id}/variables")
    enumerators = client.get(f"/api/sirl/profile/{batch_id}/enumerators")
    clusters = client.get(f"/api/sirl/profile/{batch_id}/clusters")
    districts = client.get(f"/api/sirl/profile/{batch_id}/districts")
    assert variables.status_code == 200
    assert enumerators.status_code == 200
    assert clusters.status_code == 200
    assert districts.status_code == 200

    db = SessionLocal()
    try:
        assert db.scalars(select(DatasetProfile).where(DatasetProfile.batch_id == batch_id)).first()
        assert len(db.scalars(select(VariableProfile).where(VariableProfile.batch_id == batch_id)).all()) == 10
        assert len(db.scalars(select(RecordProfile).where(RecordProfile.batch_id == batch_id)).all()) == 4
        assert len(db.scalars(select(EnumeratorProfile).where(EnumeratorProfile.batch_id == batch_id)).all()) == 2
    finally:
        db.close()


def test_sirl_statistics_match_sample() -> None:
    frame = ingest_csv_bytes((SAMPLES / "survey_sample.csv").read_bytes()).frame
    bundle = profile_frame(frame)
    assert bundle.dataset["duplicate_count"] == 0
    expected_missing = float(frame.isna().sum().sum() / (frame.shape[0] * frame.shape[1]))
    assert bundle.dataset["missing_rate"] == expected_missing

    age = next(item for item in bundle.variables if item["variable_name"] == "age")
    valid_ages = pd.to_numeric(frame["age"], errors="coerce").dropna()
    assert age["missing_count"] == 1
    assert age["mean"] == float(valid_ages.mean())
    assert age["min"] == 29
    assert age["max"] == 61

    employment = next(
        item for item in bundle.variables if item["variable_name"] == "employment_status"
    )
    assert employment["value_frequencies"]["employed"] == 3
    assert employment["value_frequencies"]["unemployed"] == 1

    ages = pd.to_numeric(frame["age"], errors="coerce")
    mean = ages.mean()
    std = ages.std(ddof=0)
    expected_z = float((34 - mean) / std)
    r001 = next(item for item in bundle.records if item["record_id"] == "R001")
    assert r001["z_scores"]["age"] == pytest.approx(expected_z)
    assert r001["missing_count"] >= 1
    e12_mean_hours = pd.to_numeric(frame.loc[frame["enumerator_id"] == "E12", "working_hours"]).mean()
    assert r001["enumerator_deviations"]["working_hours"] == pytest.approx(float(40 - e12_mean_hours))


def test_sirl_rerun_does_not_duplicate(client: TestClient, sample_csv_bytes: bytes) -> None:
    batch_id = _ingest(client, sample_csv_bytes)
    first = client.post(f"/api/sirl/profile/{batch_id}")
    second = client.post(f"/api/sirl/profile/{batch_id}")
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["reused_existing"] is True
    assert second.json()["status"] == BatchStatus.PROFILED
    db = SessionLocal()
    try:
        assert len(db.scalars(select(DatasetProfile).where(DatasetProfile.batch_id == batch_id)).all()) == 1
        assert len(db.scalars(select(VariableProfile).where(VariableProfile.batch_id == batch_id)).all()) == 10
        assert len(db.scalars(select(RecordProfile).where(RecordProfile.batch_id == batch_id)).all()) == 4
    finally:
        db.close()


def test_sirl_rejects_nonexistent_batch(client: TestClient) -> None:
    response = client.post("/api/sirl/profile/BATCH_MISSING")
    assert response.status_code == 404


def test_sirl_rejects_incomplete_batch(client: TestClient) -> None:
    batch_id = f"BATCH_NOT_COMPLETED_{uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        db.add(
            Batch(
                batch_id=batch_id,
                source="csv",
                status=BatchStatus.RECEIVED,
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
    finally:
        db.close()
    response = client.post(f"/api/sirl/profile/{batch_id}")
    assert response.status_code == 409


def test_detect_roles_resolves_respondentid_column() -> None:
    frame = pd.DataFrame(
        {
            "respondentid": ["R1", "R2"],
            "age": [25, -5],
            "enumerator_id": ["E1", "E1"],
            "cluster_id": ["C1", "C1"],
            "district_code": ["D1", "D1"],
        }
    )
    roles = detect_roles(frame)
    assert roles.record_id == "respondentid"
