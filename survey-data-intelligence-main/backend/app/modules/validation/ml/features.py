from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.config import settings
from app.modules.sirl.profiler import ColumnRoles, detect_roles
from app.modules.sirl.schemas import SirlContext


@dataclass(frozen=True)
class MlSettings:
    n_estimators: int
    contamination: str | float
    random_state: int
    min_training_records: int
    min_features: int
    score_medium: float
    score_high: float


def load_ml_settings() -> MlSettings:
    raw = str(settings.ml_contamination).strip()
    contamination: str | float
    if raw.lower() == "auto":
        contamination = "auto"
    else:
        contamination = float(raw)
    return MlSettings(
        n_estimators=int(settings.ml_n_estimators),
        contamination=contamination,
        random_state=int(settings.ml_random_state),
        min_training_records=int(settings.ml_min_training_records),
        min_features=int(settings.ml_min_features),
        score_medium=float(settings.ml_score_medium_threshold),
        score_high=float(settings.ml_score_high_threshold),
    )


def select_ml_features(
    frame: pd.DataFrame,
    roles: ColumnRoles | None = None,
    sirl_context: SirlContext | None = None,
) -> list[str]:
    """Numeric survey measures only. Identifiers, categoricals, and free text are excluded."""
    resolved = roles or detect_roles(frame)
    excluded = set(resolved.identifiers) | set(resolved.categoricals)
    candidates = [name for name in resolved.numeric_measures if name not in excluded]
    if sirl_context is None or not sirl_context.variable_context:
        return candidates
    numeric_names = {
        name
        for name, payload in sirl_context.variable_context.items()
        if (payload or {}).get("kind") == "numeric"
    }
    return [name for name in candidates if name in numeric_names]


def numeric_matrix(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    data = {}
    for name in features:
        if name not in frame.columns:
            data[name] = pd.Series(np.nan, index=frame.index, dtype="float64")
        else:
            data[name] = pd.to_numeric(frame[name], errors="coerce")
    return pd.DataFrame(data, index=frame.index)


def fit_median_imputer(reference: pd.DataFrame, features: list[str]) -> dict[str, float]:
    """Medians from the training/reference population. Missing values are never filled with zero unless the column is entirely missing."""
    matrix = numeric_matrix(reference, features)
    medians: dict[str, float] = {}
    for name in features:
        valid = matrix[name].dropna()
        if valid.empty:
            continue
        medians[name] = float(valid.median())
    return medians


def apply_median_imputer(
    frame: pd.DataFrame,
    features: list[str],
    medians: dict[str, float],
) -> tuple[np.ndarray, list[str]]:
    usable = [name for name in features if name in medians]
    if not usable:
        return np.empty((len(frame), 0)), []
    matrix = numeric_matrix(frame, usable)
    for name in usable:
        matrix[name] = matrix[name].fillna(medians[name])
    return matrix.to_numpy(dtype=float), usable
