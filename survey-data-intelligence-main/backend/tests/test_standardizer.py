import pandas as pd
import pytest

from app.modules.ingestion.canonical import CanonicalSchemaConfig
from app.modules.ingestion.csv_ingest import ingest_csv_bytes, load_csv
from app.modules.ingestion.errors import IngestError
from app.modules.ingestion.esigma_client import MockESigmaClient, parse_esigma_payload
from app.modules.ingestion.service import ingest_esigma_payload, records_to_dataframe
from app.modules.ingestion.standardizer import standardize
from tests.conftest import SAMPLES


def _normalized_from_csv() -> pd.DataFrame:
    content = (SAMPLES / "survey_sample.csv").read_bytes()
    return ingest_csv_bytes(content).frame


def _normalized_from_esigma() -> pd.DataFrame:
    payload = MockESigmaClient(SAMPLES / "esigma_sample.json").fetch()
    return ingest_esigma_payload(payload).frame


def test_csv_json_normalized_equivalence() -> None:
    csv_frame = _normalized_from_csv()
    json_frame = _normalized_from_esigma()

    assert list(csv_frame.columns) == list(json_frame.columns)
    assert csv_frame.shape[0] == json_frame.shape[0]
    assert csv_frame.dtypes.to_dict() == json_frame.dtypes.to_dict()
    pd.testing.assert_frame_equal(csv_frame, json_frame, check_dtype=True)


def test_missing_value_normalization() -> None:
    frame = pd.DataFrame(
        {
            "value": ["x", "NA", "n/a", "null", "None", "-", "", None],
        }
    )
    result = standardize(frame).frame
    assert result["value"].isna().sum() == 7
    assert result["value"].dropna().tolist() == ["x"]


def test_deterministic_column_ordering() -> None:
    frame = pd.DataFrame(
        {
            "Zed": [1],
            "alpha": [2],
            "Middle": [3],
        }
    )
    result = standardize(frame)
    assert result.columns == ["alpha", "middle", "zed"]


def test_empty_columns_preserved_by_default() -> None:
    frame = pd.DataFrame({"keep": [1], "empty": [None]})
    result = standardize(frame).frame
    assert "empty" in result.columns


def test_empty_columns_dropped_when_configured() -> None:
    frame = pd.DataFrame({"keep": [1], "empty": [None]})
    result = standardize(frame, CanonicalSchemaConfig(drop_empty_columns=True)).frame
    assert list(result.columns) == ["keep"]


def test_load_csv_rejects_empty() -> None:
    with pytest.raises(IngestError) as exc:
        load_csv(b"")
    assert exc.value.status_code == 400


def test_parse_esigma_rejects_unsupported_structure() -> None:
    with pytest.raises(IngestError) as exc:
        parse_esigma_payload("not-a-payload")
    assert exc.value.status_code == 502


def test_records_to_dataframe_roundtrip() -> None:
    payload = MockESigmaClient(SAMPLES / "esigma_sample.json").fetch()
    frame = records_to_dataframe(payload)
    assert len(frame.index) == 4
