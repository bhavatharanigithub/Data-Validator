from __future__ import annotations

from collections.abc import Callable

import pandas as pd

SINGLE_FIELD_OPERATORS = frozenset(
    {
        "equals",
        "not_equals",
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
        "in",
        "not_in",
        "is_null",
        "is_not_null",
        "is_blank",
        "is_not_blank",
        "between",
        "not_between",
        "in_reference",
    }
)

CROSS_FIELD_OPERATORS = frozenset(
    {
        "field_equals_field",
        "field_not_equals_field",
        "field_greater_than_field",
        "field_less_than_field",
        "field_greater_than_or_equal_field",
        "field_less_than_or_equal_field",
    }
)

ALLOWED_OPERATORS = SINGLE_FIELD_OPERATORS | CROSS_FIELD_OPERATORS
NULL_OPERATORS = frozenset({"is_null", "is_not_null", "is_blank", "is_not_blank"})
NUMERIC_OPERATORS = frozenset(
    {
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
        "between",
        "not_between",
        "field_greater_than_field",
        "field_less_than_field",
        "field_greater_than_or_equal_field",
        "field_less_than_or_equal_field",
    }
)


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _as_string(series: pd.Series) -> pd.Series:
    return series.astype("string")


def _bounds(value: object) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("between/not_between requires [min, max]")
    return float(value[0]), float(value[1])


def _membership(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _is_blank(series: pd.Series) -> pd.Series:
    as_string = series.astype("string")
    stripped = as_string.str.strip()
    return series.isna() | stripped.isna() | (stripped == "")


def predicate_holds(
    series: pd.Series,
    operator: str,
    value: object = None,
    other: pd.Series | None = None,
    reference_values: list[str] | None = None,
) -> pd.Series:
    if operator not in ALLOWED_OPERATORS:
        raise ValueError(f"unsupported operator: {operator}")

    if operator == "is_null":
        return series.isna()
    if operator == "is_not_null":
        return series.notna()
    if operator == "is_blank":
        return _is_blank(series)
    if operator == "is_not_blank":
        return ~_is_blank(series)

    if operator in CROSS_FIELD_OPERATORS:
        if other is None:
            raise ValueError("cross-field operator requires second_field")
        left = _numeric(series) if operator in NUMERIC_OPERATORS else _as_string(series)
        right = _numeric(other) if operator in NUMERIC_OPERATORS else _as_string(other)
        comparable = left.notna() & right.notna()
        if operator == "field_equals_field":
            return comparable & (left == right)
        if operator == "field_not_equals_field":
            return comparable & (left != right)
        if operator == "field_greater_than_field":
            return comparable & (left > right)
        if operator == "field_less_than_field":
            return comparable & (left < right)
        if operator == "field_greater_than_or_equal_field":
            return comparable & (left >= right)
        return comparable & (left <= right)

    if operator in {"in", "not_in", "in_reference"}:
        # in_reference checks membership in a configured value list only.
        # Pairwise relationships (e.g. cluster belongs to district) are not
        # validated here and remain a future-phase concern.
        allowed = reference_values if operator == "in_reference" else _membership(value)
        present = series.notna() & _as_string(series).isin(allowed)
        return present if operator != "not_in" else series.notna() & ~_as_string(series).isin(allowed)

    if operator in {"between", "not_between"}:
        low, high = _bounds(value)
        numeric = _numeric(series)
        inside = numeric.notna() & (numeric >= low) & (numeric <= high)
        return inside if operator == "between" else numeric.notna() & ~inside

    if operator in NUMERIC_OPERATORS:
        numeric = _numeric(series)
        comparable = numeric.notna()
        threshold = float(value)
        if operator == "greater_than":
            return comparable & (numeric > threshold)
        if operator == "greater_than_or_equal":
            return comparable & (numeric >= threshold)
        if operator == "less_than":
            return comparable & (numeric < threshold)
        return comparable & (numeric <= threshold)

    comparable = series.notna()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        left = _numeric(series)
        right = float(value)
        comparable = left.notna()
    else:
        left = _as_string(series)
        right = str(value)
    if operator == "equals":
        return comparable & (left == right)
    return comparable & (left != right)


OPERATOR_LABELS: dict[str, str] = {
    "equals": "=",
    "not_equals": "!=",
    "greater_than": ">",
    "greater_than_or_equal": ">=",
    "less_than": "<",
    "less_than_or_equal": "<=",
    "in": "in",
    "not_in": "not in",
    "is_null": "is null",
    "is_not_null": "is not null",
    "is_blank": "is blank",
    "is_not_blank": "is not blank",
    "between": "between",
    "not_between": "not between",
    "in_reference": "in reference set",
    "field_equals_field": "=",
    "field_not_equals_field": "!=",
    "field_greater_than_field": ">",
    "field_less_than_field": "<",
    "field_greater_than_or_equal_field": ">=",
    "field_less_than_or_equal_field": "<=",
}

# Keep a typed map so operators stay allowlisted callables conceptually.
OPERATOR_FUNCTIONS: dict[str, Callable[..., pd.Series]] = {
    name: predicate_holds for name in ALLOWED_OPERATORS
}
