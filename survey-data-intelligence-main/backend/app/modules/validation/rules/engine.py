from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Batch, BatchStatus, RuleViolation, ValidationRule, ValidationRun
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.sirl.profiler import detect_roles
from app.modules.storage.parquet import ParquetStorage
from app.modules.validation.errors import ValidationError
from app.modules.validation.rules.evaluator import (
    Predicate,
    expected_condition,
    observed_as_text,
    violation_mask,
)
from app.modules.validation.rules.repository import load_reference_lookup, replace_rule_runs
from app.modules.validation.rules.schemas import ValidationRunResponse, ViolationOut

_INGESTED = {BatchStatus.COMPLETED, BatchStatus.PROFILED}
_GLOBAL_SURVEY_CODES = frozenset({"*", "GLOBAL"})


def _batch_survey_code(batch: Batch) -> str:
    return batch.survey_code or "DEMO"


def _enabled_rules_for_batch(db: Session, survey_code: str) -> list[ValidationRule]:
    return list(
        db.scalars(
            select(ValidationRule).where(
                ValidationRule.enabled.is_(True),
                (ValidationRule.survey_code == survey_code)
                | (ValidationRule.survey_code.in_(tuple(_GLOBAL_SURVEY_CODES))),
            )
        ).all()
    )


def _require_batch(db: Session, batch_id: str) -> Batch:
    batch = db.scalars(select(Batch).where(Batch.batch_id == batch_id)).first()
    if batch is None:
        raise ValidationError("batch not found", status_code=404)
    if batch.status not in _INGESTED:
        raise ValidationError("batch ingestion is not COMPLETED", status_code=409)
    return batch


def _predicate_from_rule(rule: ValidationRule) -> Predicate:
    return Predicate(
        field=rule.field,
        operator=rule.operator,
        value=rule.value_json,
        second_field=rule.second_field,
    )


def _when_from_rule(rule: ValidationRule) -> Predicate | None:
    if not rule.when_json:
        return None
    return Predicate(
        field=str(rule.when_json.get("field")),
        operator=str(rule.when_json.get("operator")),
        value=rule.when_json.get("value"),
        second_field=rule.when_json.get("second_field"),
    )


def _id_series(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if not column or column not in frame.columns:
        return pd.Series([None] * len(frame), index=frame.index)
    return frame[column].map(lambda value: None if pd.isna(value) else str(value))


def evaluate_frame(
    frame: pd.DataFrame,
    rules: list[ValidationRule],
    reference_lookup: dict[str, list[str]],
) -> tuple[list[dict], list[dict[str, str]]]:
    roles = detect_roles(frame)
    record_ids = _id_series(frame, roles.record_id)
    enumerator_ids = _id_series(frame, roles.enumerator_id)
    cluster_ids = _id_series(frame, roles.cluster_id)
    district_ids = _id_series(frame, roles.district_id)
    collected: list[dict] = []
    skipped: list[dict[str, str]] = []

    for rule in rules:
        then = _predicate_from_rule(rule)
        when = _when_from_rule(rule)
        result = violation_mask(frame, then, when, reference_lookup)
        if result.skipped:
            skipped.append({"rule_code": rule.rule_code, "reason": result.skipped})
            continue
        if not bool(result.mask.any()):
            continue
        subset = frame.loc[result.mask]
        for index in subset.index:
            collected.append(
                {
                    "rule_id": rule.id,
                    "rule_code": rule.rule_code,
                    "severity": rule.severity,
                    "field": rule.field,
                    "record_id": record_ids.loc[index],
                    "enumerator_id": enumerator_ids.loc[index],
                    "cluster_id": cluster_ids.loc[index],
                    "district_id": district_ids.loc[index],
                    "observed_value": observed_as_text(frame.at[index, rule.field])
                    if rule.field in frame.columns
                    else None,
                    "expected_condition": expected_condition(then)
                    if when is None
                    else f"when {expected_condition(when)} then {expected_condition(then)}",
                    "message": rule.description or f"Demonstration rule {rule.rule_code} failed.",
                }
            )
    return collected, skipped


def run_rules(
    db: Session,
    batch_id: str,
    storage: ParquetStorage | None = None,
) -> ValidationRunResponse:
    batch = _require_batch(db, batch_id)
    store = storage or ParquetStorage()
    if not store.exists(batch_id):
        raise ValidationError("parquet file was not found for batch", status_code=404)

    log_event("rule_validation_started", batch_id=batch_id)
    replace_rule_runs(db, batch_id)
    started = datetime.now(UTC)
    run = ValidationRun(
        batch_id=batch_id,
        validation_type="rules",
        status="RUNNING",
        started_at=started,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        frame = store.read(batch_id)
        rules = _enabled_rules_for_batch(db, _batch_survey_code(batch))
        lookup = load_reference_lookup(db)
        rows, skipped = evaluate_frame(frame, list(rules), lookup)
        db.add_all(
            [
                RuleViolation(
                    validation_run_id=run.id,
                    batch_id=batch_id,
                    rule_id=item["rule_id"],
                    rule_code=item["rule_code"],
                    record_id=item["record_id"],
                    enumerator_id=item["enumerator_id"],
                    cluster_id=item["cluster_id"],
                    district_id=item["district_id"],
                    severity=item["severity"],
                    field=item["field"],
                    observed_value=item["observed_value"],
                    expected_condition=item["expected_condition"],
                    message=item["message"],
                    created_at=datetime.now(UTC),
                )
                for item in rows
            ]
        )
        run.status = "COMPLETED"
        run.rules_evaluated = len(rules) - len(skipped)
        run.records_checked = int(frame.shape[0])
        run.violation_count = len(rows)
        run.skipped_rules_json = skipped
        run.completed_at = datetime.now(UTC)
        db.commit()
    except ValidationError:
        run.status = "FAILED"
        run.completed_at = datetime.now(UTC)
        db.commit()
        log_failure("rule_validation_failed", batch_id=batch_id)
        raise
    except Exception as exc:
        run.status = "FAILED"
        run.completed_at = datetime.now(UTC)
        db.commit()
        log_failure("rule_validation_failed", batch_id=batch_id)
        raise ValidationError("rule validation failed", status_code=500) from exc

    log_event(
        "rule_validation_completed",
        batch_id=batch_id,
        violations=run.violation_count,
        rules_evaluated=run.rules_evaluated,
    )
    return _summary(run, rows)


def _summary(run: ValidationRun, rows: list[dict]) -> ValidationRunResponse:
    def count(level: str) -> int:
        return sum(1 for item in rows if item["severity"] == level)

    return ValidationRunResponse(
        success=run.status == "COMPLETED",
        batch_id=run.batch_id,
        validation_run_id=run.id,
        rules_evaluated=run.rules_evaluated,
        records_checked=run.records_checked,
        violations=run.violation_count,
        critical_severity=count("CRITICAL"),
        high_severity=count("HIGH"),
        medium_severity=count("MEDIUM"),
        low_severity=count("LOW"),
        skipped_rules=run.skipped_rules_json or [],
    )


def list_violations(db: Session, run_id: int) -> list[ViolationOut]:
    rows = db.scalars(
        select(RuleViolation).where(RuleViolation.validation_run_id == run_id)
    ).all()
    return [
        ViolationOut(
            record_id=row.record_id,
            rule_code=row.rule_code,
            severity=row.severity,
            field=row.field,
            observed_value=row.observed_value,
            expected_condition=row.expected_condition,
            message=row.message,
            enumerator_id=row.enumerator_id,
            cluster_id=row.cluster_id,
            district_id=row.district_id,
        )
        for row in rows
    ]
