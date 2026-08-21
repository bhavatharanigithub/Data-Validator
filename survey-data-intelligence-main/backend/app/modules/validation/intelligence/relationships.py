from __future__ import annotations

from typing import Any

import pandas as pd

from app.models import DetectorConfig
from app.modules.sirl.profiler import ColumnRoles, json_safe
from app.modules.validation.intelligence.registry import is_enabled, thresholds
from app.modules.validation.intelligence.types import (
    AGE_CANDIDATES,
    EDUCATION_CANDIDATES,
    EMPLOYMENT_CANDIDATES,
    HOURS_CANDIDATES,
    HOUSEHOLD_CANDIDATES,
    INCOME_CANDIDATES,
    MARITAL_CANDIDATES,
    ROLE_CANDIDATES,
    UNUSUAL_PATTERN,
    Detection,
    DetectorOutcome,
    first_column,
)


def _cell(row: pd.Series, column: str | None) -> Any:
    if not column:
        return None
    value = row.get(column)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _num(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _ids(row: pd.Series, roles: ColumnRoles, household: str | None) -> dict[str, str | None]:
    rec = _cell(row, roles.record_id)
    return {
        "record_id": None if rec is None else str(rec),
        "enumerator_id": None if _cell(row, roles.enumerator_id) is None else str(_cell(row, roles.enumerator_id)),
        "cluster_id": None if _cell(row, roles.cluster_id) is None else str(_cell(row, roles.cluster_id)),
        "district_id": None if _cell(row, roles.district_id) is None else str(_cell(row, roles.district_id)),
        "household_id": None if _cell(row, household) is None else str(_cell(row, household)),
    }


def _hit(
    *,
    detector_type: str,
    explanation: str,
    ids: dict[str, str | None],
    field_name: str,
    observed: float | None,
    expected: float | None,
    extra: dict,
    severity: str = "MEDIUM",
) -> Detection:
    entity = ids.get("record_id") or "unknown"
    return Detection(
        entity_type="record",
        entity_id=str(entity),
        detector_type=detector_type,
        category="RELATIONSHIP",
        classification=UNUSUAL_PATTERN,
        severity=severity,
        explanation=explanation,
        field_name=field_name,
        observed_value=json_safe(observed),
        expected_value=json_safe(expected),
        deviation=None if observed is None or expected is None else json_safe(observed - expected),
        baseline_type="relationship_rule",
        review_required=True,
        evidence=extra,
        **ids,
    )


def evaluate_relationships(
    frame: pd.DataFrame,
    roles: ColumnRoles,
    configs: dict[str, DetectorConfig],
) -> DetectorOutcome:
    columns = list(frame.columns)
    age_col = first_column(columns, AGE_CANDIDATES)
    marital_col = first_column(columns, MARITAL_CANDIDATES)
    edu_col = first_column(columns, EDUCATION_CANDIDATES)
    emp_col = first_column(columns, EMPLOYMENT_CANDIDATES)
    hours_col = first_column(columns, HOURS_CANDIDATES)
    income_col = first_column(columns, INCOME_CANDIDATES)
    role_col = first_column(columns, ROLE_CANDIDATES)
    household_col = first_column(columns, HOUSEHOLD_CANDIDATES)
    detections: list[Detection] = []

    if not any([age_col, marital_col, edu_col, emp_col, hours_col, income_col, role_col]):
        return DetectorOutcome(available=False, skipped=True, reason="No relationship fields present")

    rel_cfg = thresholds(configs, "REL_AGE_MARITAL")
    min_marriage = float(rel_cfg.get("min_marriage_age", 18))
    edu_cfg = thresholds(configs, "REL_AGE_EDUCATION")
    postgrad_age = float(edu_cfg.get("postgraduate_min_age", 20))
    hours_cfg = thresholds(configs, "REL_EMPLOYMENT_HOURS")
    not_working_hours = float(hours_cfg.get("not_working_hours_threshold", 10))
    head_cfg = thresholds(configs, "REL_AGE_HOUSEHOLD_ROLE")
    min_head = float(head_cfg.get("min_head_age", 16))
    income_cfg = thresholds(configs, "REL_INCOME_EMPLOYMENT")
    high_income = float(income_cfg.get("unemployed_high_income", 80000))

    for _, row in frame.iterrows():
        ids = _ids(row, roles, household_col)
        age = _num(_cell(row, age_col))
        marital = _text(_cell(row, marital_col))
        education = _text(_cell(row, edu_col))
        employment = _text(_cell(row, emp_col))
        hours = _num(_cell(row, hours_col))
        income = _num(_cell(row, income_col))
        role = _text(_cell(row, role_col))

        if (
            is_enabled(configs, "REL_AGE_MARITAL")
            and age is not None
            and age < min_marriage
            and "married" in marital
            and "unmarried" not in marital
            and "never" not in marital
        ):
            detections.append(
                _hit(
                    detector_type="REL_AGE_MARITAL",
                    explanation="Age and marital-status combination is unusual and requires review.",
                    ids=ids,
                    field_name=age_col or "age",
                    observed=age,
                    expected=min_marriage,
                    extra={"marital_status": marital, "rule_id": "RULE_REL_001"},
                )
            )
        if (
            is_enabled(configs, "REL_AGE_EDUCATION")
            and age is not None
            and age < postgrad_age
            and any(token in education for token in ("postgrad", "phd", "doctor", "master"))
        ):
            detections.append(
                _hit(
                    detector_type="REL_AGE_EDUCATION",
                    explanation="Age and education combination is unusual and requires review.",
                    ids=ids,
                    field_name=edu_col or "education",
                    observed=age,
                    expected=postgrad_age,
                    extra={"education": education, "rule_id": "RULE_REL_002"},
                )
            )
        not_working = any(token in employment for token in ("unemploy", "nilf", "not working", "inactive"))
        if (
            is_enabled(configs, "REL_EMPLOYMENT_HOURS")
            and not_working
            and hours is not None
            and hours > not_working_hours
        ):
            detections.append(
                _hit(
                    detector_type="REL_EMPLOYMENT_HOURS",
                    explanation="Employment status indicates not working, but working hours exceed the review threshold.",
                    ids=ids,
                    field_name=hours_col or "working_hours",
                    observed=hours,
                    expected=not_working_hours,
                    extra={"employment_status": employment, "rule_id": "RULE_REL_003"},
                )
            )
        if (
            is_enabled(configs, "REL_AGE_HOUSEHOLD_ROLE")
            and age is not None
            and age < min_head
            and role in {"head", "household head", "hhh"}
        ):
            detections.append(
                _hit(
                    detector_type="REL_AGE_HOUSEHOLD_ROLE",
                    explanation="Very young respondent listed as household head — unusual pattern, not automatically invalid.",
                    ids=ids,
                    field_name=role_col or "household_role",
                    observed=age,
                    expected=min_head,
                    extra={"household_role": role, "rule_id": "RULE_REL_004"},
                )
            )
        if (
            is_enabled(configs, "REL_INCOME_EMPLOYMENT")
            and "unemploy" in employment
            and income is not None
            and income >= high_income
        ):
            detections.append(
                _hit(
                    detector_type="REL_INCOME_EMPLOYMENT",
                    explanation="Unemployed status with unusually high income requires review. Income can have legitimate sources.",
                    ids=ids,
                    field_name=income_col or "income",
                    observed=income,
                    expected=high_income,
                    extra={"employment_status": employment, "rule_id": "RULE_REL_005"},
                )
            )
        if (
            is_enabled(configs, "REL_HOURS_EMPLOYMENT")
            and hours is not None
            and hours > 0
            and not_working
        ):
            detections.append(
                _hit(
                    detector_type="REL_HOURS_EMPLOYMENT",
                    explanation="Working hours are positive while employment status is inconsistent with work.",
                    ids=ids,
                    field_name=hours_col or "working_hours",
                    observed=hours,
                    expected=0.0,
                    extra={"employment_status": employment, "rule_id": "RULE_REL_006"},
                )
            )

    if is_enabled(configs, "REL_HOUSEHOLD_CONSISTENCY"):
        if not household_col:
            pass
        else:
            grouped = frame.groupby(frame[household_col].astype(str), dropna=True)
            for hh_id, subset in grouped:
                if str(hh_id) in {"nan", "None", ""}:
                    continue
                if role_col and role_col in subset.columns:
                    heads = subset[role_col].astype(str).str.lower().isin(["head", "household head", "hhh"]).sum()
                    if int(heads) > 1:
                        first = subset.iloc[0]
                        ids = _ids(first, roles, household_col)
                        ids["household_id"] = str(hh_id)
                        detections.append(
                            Detection(
                                entity_type="household",
                                entity_id=str(hh_id),
                                detector_type="REL_HOUSEHOLD_CONSISTENCY",
                                category="RELATIONSHIP",
                                classification=UNUSUAL_PATTERN,
                                severity="MEDIUM",
                                explanation="Multiple household heads were recorded for the same household.",
                                household_id=str(hh_id),
                                enumerator_id=ids.get("enumerator_id"),
                                cluster_id=ids.get("cluster_id"),
                                district_id=ids.get("district_id"),
                                field_name=role_col,
                                observed_value=float(heads),
                                expected_value=1.0,
                                deviation=float(heads) - 1.0,
                                baseline_type="household_structure",
                                evidence={"rule_id": "RULE_REL_007", "head_count": int(heads)},
                            )
                        )
                if age_col and age_col in subset.columns and len(subset) >= 2:
                    ages = pd.to_numeric(subset[age_col], errors="coerce").dropna()
                    if len(ages) >= 2 and float(ages.max() - ages.min()) > 90:
                        first = subset.iloc[0]
                        ids = _ids(first, roles, household_col)
                        detections.append(
                            Detection(
                                entity_type="household",
                                entity_id=str(hh_id),
                                detector_type="REL_HOUSEHOLD_CONSISTENCY",
                                category="RELATIONSHIP",
                                classification=UNUSUAL_PATTERN,
                                severity="LOW",
                                explanation="Household age span is unusually wide and should be reviewed.",
                                household_id=str(hh_id),
                                cluster_id=ids.get("cluster_id"),
                                district_id=ids.get("district_id"),
                                field_name=age_col,
                                observed_value=float(ages.max() - ages.min()),
                                expected_value=90.0,
                                baseline_type="household_structure",
                                evidence={"rule_id": "RULE_REL_007"},
                            )
                        )

    arith_enabled = is_enabled(configs, "REL_ARITHMETIC")
    total_col = first_column(columns, ("total_income", "income_total"))
    parts = [name for name in ("wage_income", "self_employment_income", "other_income") if name in frame.columns]
    if arith_enabled and total_col and parts:
        tol = float(thresholds(configs, "REL_ARITHMETIC").get("tolerance", 1.0))
        for _, row in frame.iterrows():
            total = _num(_cell(row, total_col))
            if total is None:
                continue
            summed = sum(_num(_cell(row, name)) or 0.0 for name in parts)
            if abs(total - summed) > tol:
                ids = _ids(row, roles, household_col)
                detections.append(
                    _hit(
                        detector_type="REL_ARITHMETIC",
                        explanation="Reported total does not match the sum of component fields within tolerance.",
                        ids=ids,
                        field_name=total_col,
                        observed=total,
                        expected=summed,
                        extra={"rule_id": "RULE_REL_008", "components": parts},
                    )
                )
    elif arith_enabled and not (total_col and parts):
        # Framework present; current schema has no component totals.
        pass

    return DetectorOutcome(available=True, detections=detections)
