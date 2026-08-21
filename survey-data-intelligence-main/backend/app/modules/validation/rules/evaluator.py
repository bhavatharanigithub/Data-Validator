from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.modules.sirl.profiler import json_safe
from app.modules.validation.rules.operators import (
    ALLOWED_OPERATORS,
    CROSS_FIELD_OPERATORS,
    NULL_OPERATORS,
    OPERATOR_LABELS,
    predicate_holds,
)


@dataclass(frozen=True)
class Predicate:
    field: str
    operator: str
    value: object = None
    second_field: str | None = None


@dataclass
class RuleEvalResult:
    mask: pd.Series
    skipped: str | None = None


def expected_condition(pred: Predicate) -> str:
    label = OPERATOR_LABELS.get(pred.operator, pred.operator)
    if pred.operator in CROSS_FIELD_OPERATORS:
        return f"{pred.field} {label} {pred.second_field}"
    if pred.operator in NULL_OPERATORS:
        return f"{pred.field} {label}"
    return f"{pred.field} {label} {pred.value}"


def evaluate_predicate(
    frame: pd.DataFrame,
    pred: Predicate,
    reference_lookup: dict[str, list[str]] | None = None,
) -> RuleEvalResult:
    if pred.operator not in ALLOWED_OPERATORS:
        return RuleEvalResult(mask=pd.Series(False, index=frame.index), skipped="invalid operator")
    if pred.field not in frame.columns:
        return RuleEvalResult(mask=pd.Series(False, index=frame.index), skipped="missing field")
    other = None
    if pred.operator in CROSS_FIELD_OPERATORS:
        if not pred.second_field:
            return RuleEvalResult(mask=pd.Series(False, index=frame.index), skipped="missing second_field")
        if pred.second_field not in frame.columns:
            return RuleEvalResult(mask=pd.Series(False, index=frame.index), skipped="missing second_field")
        other = frame[pred.second_field]
    reference_values = None
    if pred.operator == "in_reference":
        set_code = str(pred.value)
        reference_values = (reference_lookup or {}).get(set_code)
        if reference_values is None:
            return RuleEvalResult(
                mask=pd.Series(False, index=frame.index),
                skipped="unknown reference set",
            )
    try:
        holds = predicate_holds(
            frame[pred.field],
            pred.operator,
            pred.value,
            other=other,
            reference_values=reference_values,
        )
    except (TypeError, ValueError) as exc:
        return RuleEvalResult(mask=pd.Series(False, index=frame.index), skipped=str(exc))
    return RuleEvalResult(mask=holds.reindex(frame.index).fillna(False))


def violation_mask(
    frame: pd.DataFrame,
    then: Predicate,
    when: Predicate | None,
    reference_lookup: dict[str, list[str]] | None = None,
) -> RuleEvalResult:
    then_result = evaluate_predicate(frame, then, reference_lookup)
    if then_result.skipped:
        return then_result
    if when is None:
        if then.operator in NULL_OPERATORS:
            failed = ~then_result.mask
        else:
            failed = frame[then.field].notna() & ~then_result.mask
            if then.operator in CROSS_FIELD_OPERATORS and then.second_field:
                failed = (
                    frame[then.field].notna()
                    & frame[then.second_field].notna()
                    & ~then_result.mask
                )
        return RuleEvalResult(mask=failed)
    when_result = evaluate_predicate(frame, when, reference_lookup)
    if when_result.skipped:
        return when_result
    failed = when_result.mask & ~then_result.mask
    return RuleEvalResult(mask=failed)


def observed_as_text(value: object) -> str | None:
    safe = json_safe(value)
    if safe is None:
        return None
    return str(safe)
