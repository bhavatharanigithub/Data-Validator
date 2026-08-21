from __future__ import annotations

import json
from typing import Any

from app.modules.sirl.schemas import SirlContext


def _size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, default=str).encode("utf-8"))


def _trim_distributions(distributions: dict[str, Any], top_n: int = 3) -> dict[str, Any]:
    trimmed: dict[str, Any] = {}
    for column, counts in distributions.items():
        if not isinstance(counts, dict):
            continue
        ranked = sorted(counts.items(), key=lambda item: -int(item[1] or 0))[:top_n]
        trimmed[column] = {str(key): int(value) for key, value in ranked}
    return trimmed


def _compact_group(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "record_count": item.get("record_count"),
        "missingness_rate": item.get("missingness_rate"),
        "numeric_means": item.get("numeric_means") or {},
        "categorical_distributions": _trim_distributions(
            item.get("categorical_distributions") or {}
        ),
    }


def _rank_groups(groups: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    items = [payload for payload in groups.values() if isinstance(payload, dict)]
    items.sort(
        key=lambda item: (
            -float(item.get("missingness_rate") or 0),
            -int(item.get("record_count") or 0),
        )
    )
    return [_compact_group(item) for item in items[:limit]]


def _compact_variable(item: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "name": item.get("variable_name") or item.get("name"),
        "kind": item.get("kind"),
        "dtype": item.get("dtype"),
        "missing_rate": item.get("missing_rate"),
        "missing_count": item.get("missing_count"),
        "unique_count": item.get("unique_count"),
    }
    if item.get("kind") == "numeric":
        compact.update(
            {
                "mean": item.get("mean"),
                "std": item.get("standard_deviation"),
                "min": item.get("min"),
                "max": item.get("max"),
            }
        )
    else:
        frequencies = item.get("value_frequencies") or {}
        ranked = sorted(frequencies.items(), key=lambda pair: -int(pair[1] or 0))[:5]
        compact["top_values"] = [{"value": str(k), "count": int(v)} for k, v in ranked]
    return compact


def _rank_variables(variables: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    items = [payload for payload in variables.values() if isinstance(payload, dict)]
    items.sort(key=lambda item: -float(item.get("missing_rate") or 0))
    return [_compact_variable(item) for item in items[:limit]]


def _record_highlights(records: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    highlights: list[dict[str, Any]] = []
    for record in records:
        z_scores = record.get("z_scores") or {}
        best_var = None
        best_abs = 0.0
        best_z = None
        for name, score in z_scores.items():
            if score is None:
                continue
            try:
                numeric = abs(float(score))
            except (TypeError, ValueError):
                continue
            if numeric >= best_abs:
                best_abs = numeric
                best_var = name
                best_z = float(score)
        highlights.append(
            {
                "record_id": record.get("record_id"),
                "variable": best_var,
                "z": best_z,
                "missing_count": record.get("missing_count"),
            }
        )
    highlights.sort(key=lambda item: (-abs(float(item["z"] or 0)), -int(item.get("missing_count") or 0)))
    return highlights[:limit]


def _dataset_summary(dataset: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_count": dataset.get("record_count"),
        "column_count": dataset.get("column_count"),
        "missing_rate": dataset.get("missing_rate"),
        "duplicate_count": dataset.get("duplicate_count"),
        "numeric_measures": dataset.get("numeric_measures") or [],
        "categorical_columns": dataset.get("categorical_columns") or [],
    }


def _historical_summary(historical: dict[str, Any], limit: int = 3) -> dict[str, Any]:
    priors = historical.get("priors") or []
    compact_priors = []
    for prior in priors[:limit]:
        stats = prior.get("stats") or {}
        compact_priors.append(
            {
                "batch_id": prior.get("batch_id"),
                "record_count": stats.get("record_count"),
                "missing_rate": stats.get("missing_rate"),
            }
        )
    return {
        "historical_context_available": bool(historical.get("historical_context_available")),
        "priors": compact_priors,
    }


class ContextSelector:
    def __init__(self, max_bytes: int = 16384) -> None:
        self.max_bytes = max_bytes

    def select(self, context: SirlContext) -> dict[str, Any]:
        payload = {
            "batch_id": context.batch_id,
            "dataset_context": _dataset_summary(context.dataset_context),
            "important_variables": _rank_variables(context.variable_context, 20),
            "enumerator_context": _rank_groups(context.enumerator_context, 10),
            "cluster_context": _rank_groups(context.cluster_context, 10),
            "district_context": _rank_groups(context.district_context, 10),
            "historical_context": _historical_summary(context.historical_context),
            "record_feature_highlights": _record_highlights(context.record_context, 5),
        }
        if _size(payload) <= self.max_bytes:
            return payload
        payload.pop("record_feature_highlights", None)
        if _size(payload) <= self.max_bytes:
            return payload
        for key, cap in (
            ("district_context", 3),
            ("cluster_context", 3),
            ("enumerator_context", 3),
            ("important_variables", 8),
        ):
            payload[key] = payload[key][:cap]
            if _size(payload) <= self.max_bytes:
                return payload
        payload["historical_context"] = {
            "historical_context_available": bool(
                context.historical_context.get("historical_context_available")
            ),
            "priors": [],
        }
        return payload
