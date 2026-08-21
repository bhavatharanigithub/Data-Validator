from uuid import uuid4

import pandas as pd
import pytest

from app.db import SessionLocal, init_db
from app.models import Batch, BatchStatus
from app.modules.ingestion.csv_ingest import ingest_csv_bytes
from app.modules.ingestion.errors import IngestError
from app.modules.storage.parquet import ParquetStorage
from app.modules.storage.persist import persist_standardized_result
from tests.conftest import SAMPLES


def test_dataframe_roundtrips_to_parquet(tmp_path) -> None:
    result = ingest_csv_bytes((SAMPLES / "survey_sample.csv").read_bytes())
    storage = ParquetStorage(tmp_path)
    stored = storage.write(result.frame, "BATCH_TEST_ROUNDTRIP")

    dest = tmp_path / "processed" / "BATCH_TEST_ROUNDTRIP.parquet"
    assert dest.is_file()
    assert stored.storage == "parquet"
    assert stored.records == result.frame.shape[0]
    assert stored.columns == result.frame.shape[1]

    loaded = storage.read("BATCH_TEST_ROUNDTRIP")
    assert loaded.shape[0] == result.frame.shape[0]
    assert list(loaded.columns) == list(result.frame.columns)
    pd.testing.assert_frame_equal(loaded, result.frame, check_dtype=True)


def test_parquet_write_refuses_overwrite(tmp_path) -> None:
    result = ingest_csv_bytes((SAMPLES / "survey_sample.csv").read_bytes())
    storage = ParquetStorage(tmp_path)
    storage.write(result.frame, "BATCH_DUP")
    with pytest.raises(IngestError) as exc:
        storage.write(result.frame, "BATCH_DUP")
    assert exc.value.status_code == 409
    loaded = storage.read("BATCH_DUP")
    pd.testing.assert_frame_equal(loaded, result.frame, check_dtype=True)


def test_duplicate_batch_id_allocates_new(tmp_path) -> None:
    init_db()
    result = ingest_csv_bytes((SAMPLES / "survey_sample.csv").read_bytes())
    storage = ParquetStorage(tmp_path)
    db = SessionLocal()
    try:
        first = persist_standardized_result(db, result, "csv", storage=storage)
        second = persist_standardized_result(
            db, result, "csv", storage=storage, batch_id=first.batch_id
        )
        assert second.batch_id != first.batch_id
        assert storage.exists(first.batch_id)
        assert storage.exists(second.batch_id)
        assert first.path != second.path
    finally:
        db.close()


def test_parquet_failure_marks_batch_failed(tmp_path, monkeypatch) -> None:
    init_db()
    result = ingest_csv_bytes((SAMPLES / "survey_sample.csv").read_bytes())
    storage = ParquetStorage(tmp_path)

    def boom(self, frame, batch_id):  # noqa: ANN001
        raise OSError("disk full")

    monkeypatch.setattr(ParquetStorage, "write", boom)
    fail_id = f"BATCH_FAIL_{uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        with pytest.raises(IngestError) as exc:
            persist_standardized_result(
                db, result, "csv", storage=storage, batch_id=fail_id
            )
        assert exc.value.status_code == 500
        batch = db.query(Batch).filter_by(batch_id=fail_id).one()
        assert batch.status == BatchStatus.FAILED
        assert batch.error_message
        assert batch.parquet_path is None
        assert not storage.exists(fail_id)
    finally:
        db.close()
