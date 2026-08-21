from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

RECORD_ID_CANDIDATES = ("respondent_id", "record_id", "person_id", "hh_id")
ENUMERATOR_CANDIDATES = ("enumerator_id", "enumerator")
CLUSTER_CANDIDATES = ("cluster_id", "cluster", "fsu")
DISTRICT_CANDIDATES = ("district_code", "district_id", "district")


@dataclass(frozen=True)
class ColumnRoles:
    record_id: str | None
    enumerator_id: str | None
    cluster_id: str | None
    district_id: str | None
    numeric_measures: tuple[str, ...]
    categoricals: tuple[str, ...]
    identifiers: tuple[str, ...]


@dataclass
class ProfileBundle:
    dataset: dict[str, Any]
    variables: list[dict[str, Any]]
    records: list[dict[str, Any]]
    enumerators: list[dict[str, Any]]
    clusters: list[dict[str, Any]]
    districts: list[dict[str, Any]]
    historical: dict[str, Any] = field(
        default_factory=lambda: {"historical_context_available": False, "priors": []}
    )
    profiled_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _normalize_col_key(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _first_present(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    lookup = {name.lower(): name for name in columns}
    normalized = {_normalize_col_key(name): name for name in columns}
    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]
        key = _normalize_col_key(candidate)
        if key in normalized:
            return normalized[key]
    return None


def detect_roles(frame: pd.DataFrame) -> ColumnRoles:
    columns = list(frame.columns)
    record_id = _first_present(columns, RECORD_ID_CANDIDATES)
    enumerator_id = _first_present(columns, ENUMERATOR_CANDIDATES)
    cluster_id = _first_present(columns, CLUSTER_CANDIDATES)
    district_id = _first_present(columns, DISTRICT_CANDIDATES)
    identifiers = tuple(
        col for col in (record_id, enumerator_id, cluster_id, district_id) if col
    )
    numeric_measures: list[str] = []
    categoricals: list[str] = []
    for column in columns:
        if column in identifiers:
            continue
        if _is_numeric(frame[column]):
            numeric_measures.append(column)
        else:
            categoricals.append(column)
    return ColumnRoles(
        record_id=record_id,
        enumerator_id=enumerator_id,
        cluster_id=cluster_id,
        district_id=district_id,
        numeric_measures=tuple(numeric_measures),
        categoricals=tuple(categoricals),
        identifiers=identifiers,
    )


def _is_numeric(series: pd.Series) -> bool:
    return bool(pd.api.types.is_numeric_dtype(series)) and not bool(
        pd.api.types.is_bool_dtype(series)
    )


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if np.isnan(number) or np.isinf(number):
            return None
        return number
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value if isinstance(value, (str, int)) else str(value)


def _numeric_profile(series: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(series, errors="coerce")
    missing = int(series.isna().sum())
    n = int(series.shape[0])
    valid = numeric.dropna()
    quantiles = valid.quantile([0.25, 0.5, 0.75, 0.95]) if not valid.empty else None
    return {
        "dtype": str(series.dtype),
        "kind": "numeric",
        "missing_count": missing,
        "missing_rate": missing / n if n else 0.0,
        "unique_count": int(series.nunique(dropna=True)),
        "min": json_safe(valid.min()) if not valid.empty else None,
        "max": json_safe(valid.max()) if not valid.empty else None,
        "mean": json_safe(valid.mean()) if not valid.empty else None,
        "median": json_safe(quantiles.loc[0.5]) if quantiles is not None else None,
        "standard_deviation": json_safe(valid.std(ddof=1)) if len(valid) > 1 else None,
        "p25": json_safe(quantiles.loc[0.25]) if quantiles is not None else None,
        "p75": json_safe(quantiles.loc[0.75]) if quantiles is not None else None,
        "p95": json_safe(quantiles.loc[0.95]) if quantiles is not None else None,
    }


def _categorical_profile(series: pd.Series, top_n: int = 10) -> dict[str, Any]:
    missing = int(series.isna().sum())
    n = int(series.shape[0])
    frequencies = (
        series.dropna().astype(str).value_counts().head(top_n).to_dict()
    )
    return {
        "dtype": str(series.dtype),
        "kind": "categorical",
        "missing_count": missing,
        "missing_rate": missing / n if n else 0.0,
        "unique_count": int(series.nunique(dropna=True)),
        "top_values": [{"value": str(key), "count": int(count)} for key, count in frequencies.items()],
        "value_frequencies": {str(key): int(count) for key, count in frequencies.items()},
    }


def _dataset_profile(frame: pd.DataFrame, roles: ColumnRoles, parquet_bytes: int | None) -> dict[str, Any]:
    rows, cols = int(frame.shape[0]), int(frame.shape[1])
    total_cells = rows * cols
    missing = int(frame.isna().sum().sum())
    numeric_count = sum(1 for column in frame.columns if _is_numeric(frame[column]))
    return {
        "record_count": rows,
        "column_count": cols,
        "numeric_column_count": numeric_count,
        "categorical_column_count": cols - numeric_count,
        "missing_rate": missing / total_cells if total_cells else 0.0,
        "duplicate_count": int(frame.duplicated().sum()),
        "parquet_bytes": parquet_bytes,
        "identifier_columns": list(roles.identifiers),
        "numeric_measures": list(roles.numeric_measures),
        "categorical_columns": list(roles.categoricals),
    }


def _variable_profiles(frame: pd.DataFrame) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for column in frame.columns:
        series = frame[column]
        payload = (
            _numeric_profile(series) if _is_numeric(series) else _categorical_profile(series)
        )
        payload["variable_name"] = column
        profiles.append(payload)
    return profiles


def _group_missing_rate(frame: pd.DataFrame, group_col: str) -> pd.Series:
    na_by_row = frame.isna().sum(axis=1)
    grouped = na_by_row.groupby(frame[group_col], dropna=False)
    counts = frame.groupby(group_col, dropna=False).size()
    ncols = max(int(frame.shape[1]), 1)
    return grouped.sum() / (counts * ncols)


def _group_numeric_means(frame: pd.DataFrame, group_col: str, measures: tuple[str, ...]) -> pd.DataFrame:
    if not measures:
        return pd.DataFrame(index=frame[group_col].dropna().unique())
    return frame.groupby(group_col, dropna=False)[list(measures)].mean()


def _group_categorical_distributions(
    frame: pd.DataFrame, group_col: str, categoricals: tuple[str, ...]
) -> dict[str, dict[str, dict[str, int]]]:
    result: dict[str, dict[str, dict[str, int]]] = {}
    if not categoricals:
        return result
    grouped = frame.groupby(group_col, dropna=False)
    for group_key, subset in grouped:
        key = "null" if pd.isna(group_key) else str(group_key)
        result[key] = {}
        for column in categoricals:
            counts = subset[column].dropna().astype(str).value_counts().head(10)
            result[key][column] = {str(k): int(v) for k, v in counts.items()}
    return result


def _entity_profiles(
    frame: pd.DataFrame,
    group_col: str,
    roles: ColumnRoles,
    extra: str | None = None,
) -> list[dict[str, Any]]:
    counts = frame.groupby(group_col, dropna=False).size()
    missing_rates = _group_missing_rate(frame, group_col)
    means = _group_numeric_means(frame, group_col, roles.numeric_measures)
    distributions = _group_categorical_distributions(frame, group_col, roles.categoricals)
    extras: dict[str, Any] = {}
    if extra and extra in frame.columns:
        extras = frame.groupby(group_col, dropna=False)[extra].agg(
            lambda s: json_safe(s.dropna().iloc[0]) if not s.dropna().empty else None
        ).to_dict()

    profiles: list[dict[str, Any]] = []
    for key, count in counts.items():
        label = "null" if pd.isna(key) else str(key)
        numeric_means = {}
        if not means.empty and key in means.index:
            numeric_means = {
                column: json_safe(means.loc[key, column]) for column in means.columns
            }
        profiles.append(
            {
                "id": label,
                "record_count": int(count),
                "missingness_rate": json_safe(missing_rates.loc[key]) if key in missing_rates.index else 0.0,
                "numeric_means": numeric_means,
                "categorical_distributions": distributions.get(label, {}),
                "related_id": extras.get(key) if extras else None,
                "employment_rate": _group_employment(frame, group_col, key),
            }
        )
    return profiles


def _group_employment(frame: pd.DataFrame, group_col: str, key) -> float | None:
    emp = None
    for candidate in ("employment_status", "emp_status", "activity_status"):
        if candidate in frame.columns:
            emp = candidate
            break
    if emp is None:
        return None
    subset = frame.loc[frame[group_col] == key, emp]
    values = subset.dropna().astype(str).str.lower()
    if values.empty:
        return None
    employed = values.str.contains("employ") & ~values.str.contains("unemploy")
    return json_safe(float(employed.mean()))


def _record_profiles(frame: pd.DataFrame, roles: ColumnRoles) -> list[dict[str, Any]]:
    n = int(frame.shape[0])
    missing_count = frame.isna().sum(axis=1).astype("int64")
    missing_rate = missing_count / max(int(frame.shape[1]), 1)

    z_scores = pd.DataFrame(index=frame.index)
    percentiles = pd.DataFrame(index=frame.index)
    for column in roles.numeric_measures:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        mean = numeric.mean()
        std = numeric.std(ddof=0)
        if std is None or pd.isna(std) or std == 0:
            z_scores[column] = np.nan
        else:
            z_scores[column] = (numeric - mean) / std
        percentiles[column] = numeric.rank(method="average", pct=True)

    enumerator_dev = pd.DataFrame(index=frame.index)
    cluster_dev = pd.DataFrame(index=frame.index)
    district_dev = pd.DataFrame(index=frame.index)
    for column in roles.numeric_measures:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if roles.enumerator_id:
            enumerator_dev[column] = numeric - numeric.groupby(frame[roles.enumerator_id]).transform("mean")
        if roles.cluster_id:
            cluster_dev[column] = numeric - numeric.groupby(frame[roles.cluster_id]).transform("mean")
        if roles.district_id:
            district_dev[column] = numeric - numeric.groupby(frame[roles.district_id]).transform("mean")

    if roles.record_id:
        record_ids = frame[roles.record_id].astype(str)
    else:
        record_ids = pd.Series([str(i) for i in range(n)], index=frame.index)

    enumerator_ids = (
        frame[roles.enumerator_id].map(lambda v: None if pd.isna(v) else str(v))
        if roles.enumerator_id
        else pd.Series([None] * n, index=frame.index)
    )
    cluster_ids = (
        frame[roles.cluster_id].map(lambda v: None if pd.isna(v) else str(v))
        if roles.cluster_id
        else pd.Series([None] * n, index=frame.index)
    )
    district_ids = (
        frame[roles.district_id].map(lambda v: None if pd.isna(v) else str(v))
        if roles.district_id
        else pd.Series([None] * n, index=frame.index)
    )

    values = frame.where(frame.notna(), None)
    records: list[dict[str, Any]] = []
    value_records = values.to_dict(orient="records")
    z_records = z_scores.replace({np.nan: None}).to_dict(orient="records")
    p_records = percentiles.replace({np.nan: None}).to_dict(orient="records")
    e_records = enumerator_dev.replace({np.nan: None}).to_dict(orient="records") if not enumerator_dev.empty else [{}] * n
    c_records = cluster_dev.replace({np.nan: None}).to_dict(orient="records") if not cluster_dev.empty else [{}] * n
    d_records = district_dev.replace({np.nan: None}).to_dict(orient="records") if not district_dev.empty else [{}] * n

    for i in range(n):
        records.append(
            {
                "record_id": str(record_ids.iloc[i]),
                "enumerator_id": enumerator_ids.iloc[i],
                "cluster_id": cluster_ids.iloc[i],
                "district_id": district_ids.iloc[i],
                "values": {k: json_safe(v) for k, v in value_records[i].items()},
                "missing_count": int(missing_count.iloc[i]),
                "missing_rate": float(missing_rate.iloc[i]),
                "z_scores": {k: json_safe(v) for k, v in z_records[i].items()},
                "percentiles": {k: json_safe(v) for k, v in p_records[i].items()},
                "enumerator_deviations": {k: json_safe(v) for k, v in e_records[i].items()},
                "cluster_deviations": {k: json_safe(v) for k, v in c_records[i].items()},
                "district_deviations": {k: json_safe(v) for k, v in d_records[i].items()},
                "pattern_signature": None,
                "relationship_flags": [],
                "outlier_features": [
                    name
                    for name, value in z_records[i].items()
                    if value is not None and abs(float(value)) >= 3
                ],
            }
        )
    return records


def profile_frame(
    frame: pd.DataFrame,
    parquet_bytes: int | None = None,
    historical: dict[str, Any] | None = None,
) -> ProfileBundle:
    roles = detect_roles(frame)
    dataset = _dataset_profile(frame, roles, parquet_bytes)
    variables = _variable_profiles(frame)
    records = _record_profiles(frame, roles)
    enumerators = (
        _entity_profiles(frame, roles.enumerator_id, roles) if roles.enumerator_id else []
    )
    clusters = (
        _entity_profiles(frame, roles.cluster_id, roles, extra=roles.district_id)
        if roles.cluster_id
        else []
    )
    districts = (
        _entity_profiles(frame, roles.district_id, roles) if roles.district_id else []
    )
    return ProfileBundle(
        dataset=dataset,
        variables=variables,
        records=records,
        enumerators=enumerators,
        clusters=clusters,
        districts=districts,
        historical=historical
        or {"historical_context_available": False, "priors": []},
    )
