from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.config import PROJECT_ROOT, settings
from app.modules.ingestion.errors import IngestError


@dataclass(frozen=True)
class ParquetStoreResult:
    batch_id: str
    records: int
    columns: int
    storage: str
    path: str


class ParquetStorage:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else settings.data_dir
        self.processed_dir = self.data_dir / "processed"

    def absolute_path(self, batch_id: str) -> Path:
        return self.processed_dir / f"{batch_id}.parquet"

    def public_path(self, batch_id: str) -> str:
        abs_path = self.absolute_path(batch_id).resolve()
        try:
            return str(abs_path.relative_to(PROJECT_ROOT.resolve()))
        except ValueError:
            return f"data/processed/{batch_id}.parquet"

    def exists(self, batch_id: str) -> bool:
        return self.absolute_path(batch_id).exists()

    def write(self, frame: pd.DataFrame, batch_id: str) -> ParquetStoreResult:
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        dest = self.absolute_path(batch_id)
        if dest.exists():
            raise IngestError(
                "batch parquet already exists; refusing to overwrite",
                status_code=409,
            )
        try:
            frame.to_parquet(dest, engine="pyarrow", index=False)
        except IngestError:
            raise
        except Exception as exc:
            if dest.exists():
                dest.unlink(missing_ok=True)
            raise IngestError("Parquet storage failed", status_code=500) from exc

        return ParquetStoreResult(
            batch_id=batch_id,
            records=int(frame.shape[0]),
            columns=int(frame.shape[1]),
            storage="parquet",
            path=self.public_path(batch_id),
        )

    def read(self, batch_id: str) -> pd.DataFrame:
        dest = self.absolute_path(batch_id)
        if not dest.exists():
            raise IngestError("parquet file was not found", status_code=404)
        return pd.read_parquet(dest, engine="pyarrow")
