from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Batch, BatchStatus
from app.modules.storage.parquet import ParquetStorage

_READABLE = {BatchStatus.COMPLETED, BatchStatus.PROFILED}


def load_historical_frames(
    db: Session,
    current_batch_id: str,
    storage: ParquetStorage,
) -> list[pd.DataFrame]:
    """Parquet from previously ingested batches only. Never includes the current batch."""
    rows = db.scalars(
        select(Batch).where(
            Batch.batch_id != current_batch_id,
            Batch.status.in_(tuple(_READABLE)),
        )
    ).all()
    frames: list[pd.DataFrame] = []
    for batch in rows:
        if batch.batch_id == current_batch_id:
            continue
        if not storage.exists(batch.batch_id):
            continue
        frames.append(storage.read(batch.batch_id))
    return frames


def combine_reference(frames: list[pd.DataFrame], features: list[str]) -> pd.DataFrame | None:
    parts: list[pd.DataFrame] = []
    for frame in frames:
        if all(name in frame.columns for name in features):
            parts.append(frame[features])
    if not parts:
        return None
    return pd.concat(parts, ignore_index=True)
