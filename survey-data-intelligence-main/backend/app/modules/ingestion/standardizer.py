from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from app.modules.ingestion.canonical import (
    CANONICAL_SCHEMA_VERSION,
    DEFAULT_SCHEMA,
    MISSING_TOKENS,
    CanonicalSchemaConfig,
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class StandardizedResult:
    frame: pd.DataFrame
    schema_version: str
    columns: list[str]
    dtypes: dict[str, str]


def normalize_column_name(name: object) -> str:
    raw = str(name).strip().lower()
    raw = _NON_ALNUM.sub("_", raw).strip("_")
    return raw or "column"


def _dedupe_columns(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique: list[str] = []
    for name in names:
        count = seen.get(name, 0)
        seen[name] = count + 1
        unique.append(name if count == 0 else f"{name}_{count + 1}")
    return unique


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and value.strip().lower() in MISSING_TOKENS:
        return True
    return False


def _normalize_series_missing_and_whitespace(series: pd.Series) -> pd.Series:
    def clean(value: object) -> object:
        if _is_missing(value):
            return pd.NA
        if isinstance(value, str):
            return value.strip()
        return value

    return series.map(clean)


def _maybe_numeric(series: pd.Series) -> pd.Series:
    non_missing = series.dropna()
    if non_missing.empty:
        return series.astype("string")

    numeric = pd.to_numeric(series, errors="coerce")
    compatible_mask = series.isna() | numeric.notna()
    if not bool(compatible_mask.all()):
        return series.astype("string")

    numeric_non_missing = numeric.dropna()
    if numeric_non_missing.empty:
        return series.astype("string")

    whole = (numeric_non_missing % 1 == 0).all()
    if whole:
        return numeric.round().astype("Int64")
    return numeric.astype("Float64")


class Standardizer:
    def __init__(self, schema: CanonicalSchemaConfig | None = None) -> None:
        self.schema = schema or DEFAULT_SCHEMA

    def standardize(self, frame: pd.DataFrame) -> StandardizedResult:
        if frame.empty and frame.columns.empty:
            raise ValueError("dataset has no columns")

        renamed = [
            self.schema.column_aliases.get(normalize_column_name(col), normalize_column_name(col))
            for col in frame.columns
        ]
        working = frame.copy()
        working.columns = _dedupe_columns(renamed)
        working = working.reindex(sorted(working.columns), axis=1)

        cleaned = pd.DataFrame(index=working.index)
        for column in working.columns:
            series = _normalize_series_missing_and_whitespace(working[column])
            cleaned[column] = _maybe_numeric(series)

        if self.schema.drop_empty_columns:
            non_empty = [col for col in cleaned.columns if cleaned[col].notna().any()]
            cleaned = cleaned.loc[:, non_empty]

        dtypes = {col: str(cleaned[col].dtype) for col in cleaned.columns}
        return StandardizedResult(
            frame=cleaned,
            schema_version=self.schema.schema_version or CANONICAL_SCHEMA_VERSION,
            columns=list(cleaned.columns),
            dtypes=dtypes,
        )


def standardize(
    frame: pd.DataFrame, schema: CanonicalSchemaConfig | None = None
) -> StandardizedResult:
    return Standardizer(schema).standardize(frame)
