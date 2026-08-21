from __future__ import annotations

import pandas as pd

from app.modules.ingestion.errors import IngestError
from app.modules.ingestion.esigma_client import ESigmaClient, build_esigma_client
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.ingestion.schemas import ESigmaPayload
from app.modules.ingestion.standardizer import StandardizedResult, standardize


def records_to_dataframe(payload: ESigmaPayload) -> pd.DataFrame:
    return pd.DataFrame.from_records(payload.records)


def ingest_esigma_payload(payload: ESigmaPayload) -> StandardizedResult:
    frame = records_to_dataframe(payload)
    if frame.empty:
        raise IngestError("eSIGMA response has no records", status_code=400)
    return standardize(frame)


def ingest_from_esigma(
    client: ESigmaClient | None = None, path: str | None = None
) -> StandardizedResult:
    log_event("ingestion_started", source="esigma")
    active = client or build_esigma_client()
    try:
        payload = active.fetch(path)
        result = ingest_esigma_payload(payload)
    except IngestError:
        log_failure("ingestion_failure", source="esigma")
        raise
    except Exception:
        log_failure("ingestion_failure", source="esigma")
        raise IngestError("eSIGMA ingestion failed", status_code=502) from None

    log_event(
        "standardization_completed",
        source="esigma",
        rows=int(result.frame.shape[0]),
        columns=int(result.frame.shape[1]),
    )
    return result
