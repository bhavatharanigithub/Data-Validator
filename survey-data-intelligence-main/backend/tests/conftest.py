import os
import tempfile
from pathlib import Path

_TEST_DB = Path(tempfile.mkdtemp(prefix="sv-pytest-")) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["JWT_SECRET"] = "pytest-jwt-secret-key-must-be-32b"
os.environ["AI_BASE_URL"] = ""
os.environ["AI_API_KEY"] = ""
os.environ["AI_MODEL"] = ""
os.environ["AI_PROVIDER"] = ""
os.environ["PIPELINE_SYNC_JOBS"] = "true"
os.environ["INGEST_REUSE_COMPLETED"] = "false"
os.environ["MAX_CONCURRENT_PIPELINES"] = "1"

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import PROJECT_ROOT, settings
from app.db import init_db
from app.main import app

settings.pipeline_sync_jobs = True
settings.ingest_reuse_completed = False
settings.max_concurrent_pipelines = 1
settings.ai_base_url = ""
settings.ai_api_key = ""
settings.ai_model = ""
settings.ai_provider = ""

SAMPLES = PROJECT_ROOT / "data" / "samples"


@pytest.fixture(autouse=True)
def _ensure_database() -> None:
    init_db()


@pytest.fixture
def anon_client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        assert response.status_code == 200, response.text
        yield test_client


@pytest.fixture
def supervisor_client() -> TestClient:
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/auth/login",
            json={"username": "supervisor", "password": "supervisor"},
        )
        assert response.status_code == 200, response.text
        yield test_client


@pytest.fixture
def sample_csv_bytes() -> bytes:
    return (SAMPLES / "survey_sample.csv").read_bytes()


@pytest.fixture
def sample_csv_frame() -> pd.DataFrame:
    return pd.read_csv(SAMPLES / "survey_sample.csv")
