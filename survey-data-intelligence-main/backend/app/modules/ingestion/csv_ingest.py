from __future__ import annotations

import io

import pandas as pd
from pandas.errors import EmptyDataError, ParserError

from app.modules.ingestion.errors import IngestError
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.ingestion.standardizer import StandardizedResult, standardize


def load_csv(content: bytes) -> pd.DataFrame:
    if not content or not content.strip():
        raise IngestError("CSV file is empty", status_code=400)
    try:
        frame = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
    except EmptyDataError as exc:
        raise IngestError("CSV file is empty", status_code=400) from exc
    except (ParserError, UnicodeDecodeError) as exc:
        raise IngestError("CSV file is not readable", status_code=400) from exc
    except Exception as exc:
        raise IngestError("CSV file is not readable", status_code=400) from exc

    if frame.columns.size == 0:
        raise IngestError("CSV file is empty", status_code=400)
    if len(frame.index) == 0:
        raise IngestError("CSV file has no data rows", status_code=400)
    return frame


def ingest_csv_bytes(content: bytes) -> StandardizedResult:
    log_event("ingestion_started", source="csv")
    try:
        frame = load_csv(content)
        result = standardize(frame)
    except IngestError:
        log_failure("ingestion_failure", source="csv")
        raise
    except Exception:
        log_failure("ingestion_failure", source="csv")
        raise IngestError("CSV ingestion failed", status_code=400) from None

    log_event(
        "standardization_completed",
        source="csv",
        rows=int(result.frame.shape[0]),
        columns=int(result.frame.shape[1]),
    )
    return result
