from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import HistoricalProfile, VariableProfile
from app.modules.sirl.profiler import ColumnRoles, detect_roles
from app.modules.sirl.schemas import SirlContext


@dataclass(frozen=True)
class StatsThresholds:
    z_medium: float
    z_high: float
    iqr_multiplier: float
    iqr_outer_multiplier: float
    min_observations: int
    min_group_observations: int
    std_epsilon: float
    historical_relative_medium: float
    historical_relative_high: float


def load_thresholds() -> StatsThresholds:
    return StatsThresholds(
        z_medium=float(settings.stats_z_medium_threshold),
        z_high=float(settings.stats_z_high_threshold),
        iqr_multiplier=float(settings.stats_iqr_multiplier),
        iqr_outer_multiplier=float(settings.stats_iqr_outer_multiplier),
        min_observations=int(settings.stats_min_observations),
        min_group_observations=int(settings.stats_min_group_observations),
        std_epsilon=float(settings.stats_std_epsilon),
        historical_relative_medium=float(settings.stats_historical_relative_medium),
        historical_relative_high=float(settings.stats_historical_relative_high),
    )


def eligible_variables(
    frame: pd.DataFrame,
    roles: ColumnRoles | None = None,
    sirl_context: SirlContext | None = None,
) -> list[str]:
    """Numeric survey measures only. Identifiers and free text are excluded."""
    resolved = roles or detect_roles(frame)
    excluded = set(resolved.identifiers)
    candidates = [name for name in resolved.numeric_measures if name not in excluded]
    if sirl_context is None or not sirl_context.variable_context:
        return candidates
    numeric_names = {
        name
        for name, payload in sirl_context.variable_context.items()
        if (payload or {}).get("kind") == "numeric"
    }
    return [name for name in candidates if name in numeric_names]


def usable_std(std: float | None, epsilon: float) -> bool:
    if std is None:
        return False
    try:
        value = float(std)
    except (TypeError, ValueError):
        return False
    return value == value and abs(value) >= epsilon


def load_historical_baselines(
    db: Session,
    batch_id: str,
    variables: list[str],
) -> tuple[dict[str, dict[str, float | str | None]], bool]:
    """Use previously profiled batches only. Never treat the current batch as history."""
    priors = db.scalars(
        select(HistoricalProfile)
        .where(
            HistoricalProfile.grain == "dataset",
            HistoricalProfile.batch_id != batch_id,
        )
        .order_by(HistoricalProfile.created_at.desc())
    ).all()
    wanted = set(variables)
    baseline: dict[str, dict[str, float | str | None]] = {}
    for prior in priors:
        if prior.batch_id == batch_id:
            continue
        profiles = db.scalars(
            select(VariableProfile).where(VariableProfile.batch_id == prior.batch_id)
        ).all()
        for profile in profiles:
            if (
                profile.kind != "numeric"
                or profile.variable_name not in wanted
                or profile.variable_name in baseline
            ):
                continue
            payload = profile.profile_json or {}
            mean = payload.get("mean")
            if mean is None:
                continue
            baseline[profile.variable_name] = {
                "mean": float(mean),
                "std": None
                if payload.get("standard_deviation") is None
                else float(payload["standard_deviation"]),
                "source_batch_id": prior.batch_id,
            }
        if len(baseline) == len(wanted):
            break
    return baseline, bool(baseline)
