"""Isolation Forest scoring.

sklearn IsolationForest.score_samples: lower means more abnormal.

This module converts that to a 0–100 anomaly score where HIGHER means more
anomalous relative to the training population.

Normalization (not a probability):
  raw = -score_samples(X)
  lo, hi = 1st and 99th percentiles of raw scores on the training matrix
  anomaly_score = clip((raw - lo) / (hi - lo) * 100, 0, 100)

A score of 91/100 means a high relative Isolation Forest anomaly score for
this configuration, not a 91% chance the record is wrong.

Severity (ML only, not fused with rules/statistics):
  < medium threshold -> LOW
  medium <= score < high -> MEDIUM
  >= high -> HIGH
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import IsolationForest
import sklearn

from app.modules.validation.ml.features import MlSettings

MODEL_TYPE = "isolation_forest"
MODEL_VERSION = "isolation_forest-v1"


@dataclass(frozen=True)
class FittedIsolationForest:
    model: IsolationForest
    train_raw: np.ndarray
    lo: float
    hi: float
    settings: MlSettings


def _contamination(settings: MlSettings) -> str | float:
    return settings.contamination


def train_isolation_forest(X_train: np.ndarray, settings: MlSettings) -> FittedIsolationForest:
    model = IsolationForest(
        n_estimators=settings.n_estimators,
        contamination=_contamination(settings),
        random_state=settings.random_state,
        n_jobs=1,
    )
    model.fit(X_train)
    train_raw = -model.score_samples(X_train)
    lo = float(np.percentile(train_raw, 1))
    hi = float(np.percentile(train_raw, 99))
    if not np.isfinite(lo):
        lo = 0.0
    if not np.isfinite(hi):
        hi = lo
    return FittedIsolationForest(model=model, train_raw=train_raw, lo=lo, hi=hi, settings=settings)


def normalize_anomaly_scores(raw: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Map higher-is-anomalous raw scores onto 0–100 using training percentiles."""
    span = hi - lo
    if not np.isfinite(span) or abs(span) < 1e-12:
        return np.zeros(raw.shape[0], dtype=float)
    scaled = (raw - lo) / span * 100.0
    return np.clip(scaled, 0.0, 100.0)


def ml_severity(score: float, settings: MlSettings) -> str:
    if score >= settings.score_high:
        return "HIGH"
    if score >= settings.score_medium:
        return "MEDIUM"
    return "LOW"


def infer(fitted: FittedIsolationForest, X_current: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (raw sklearn score_samples, 0–100 anomaly scores, predict labels)."""
    score_samples = fitted.model.score_samples(X_current)
    raw = -score_samples
    scores = normalize_anomaly_scores(raw, fitted.lo, fitted.hi)
    labels = fitted.model.predict(X_current)
    return score_samples, scores, labels


def model_configuration(settings: MlSettings) -> dict:
    return {
        "algorithm": MODEL_TYPE,
        "model_version": MODEL_VERSION,
        "sklearn_version": sklearn.__version__,
        "n_estimators": settings.n_estimators,
        "contamination": settings.contamination,
        "random_state": settings.random_state,
    }
