from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RuleViolation, ValidationReferenceSet, ValidationRule, ValidationRun
from app.modules.validation.errors import ValidationError
from app.modules.validation.rules.schemas import RuleCreate, RuleOut, RuleUpdate


def _to_out(rule: ValidationRule) -> RuleOut:
    return RuleOut(
        id=rule.id,
        rule_code=rule.rule_code,
        survey_code=rule.survey_code,
        name=rule.name,
        description=rule.description,
        field=rule.field,
        operator=rule.operator,
        value=rule.value_json,
        second_field=rule.second_field,
        when=rule.when_json,
        severity=rule.severity,
        scope=rule.scope,
        enabled=rule.enabled,
        version=rule.version,
        is_sample=rule.is_sample,
        created_by=rule.created_by,
    )


def create_rule(db: Session, payload: RuleCreate) -> RuleOut:
    existing = db.scalars(
        select(ValidationRule).where(ValidationRule.rule_code == payload.rule_code)
    ).first()
    if existing is not None:
        raise ValidationError("rule_code already exists", status_code=409)
    rule = ValidationRule(
        rule_code=payload.rule_code,
        survey_code=payload.survey_code,
        name=payload.name,
        description=payload.description,
        field=payload.field,
        operator=payload.operator,
        value_json=payload.value,
        second_field=payload.second_field,
        when_json=payload.when.model_dump() if payload.when else None,
        severity=payload.severity,
        scope=payload.scope,
        enabled=payload.enabled,
        is_sample=payload.is_sample,
        created_by=payload.created_by,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


def list_rules(db: Session, enabled: bool | None = None) -> list[RuleOut]:
    query = select(ValidationRule).order_by(ValidationRule.id)
    if enabled is not None:
        query = query.where(ValidationRule.enabled.is_(enabled))
    return [_to_out(rule) for rule in db.scalars(query).all()]


def get_rule(db: Session, rule_id: int) -> ValidationRule:
    rule = db.get(ValidationRule, rule_id)
    if rule is None:
        raise ValidationError("rule not found", status_code=404)
    return rule


def get_rule_out(db: Session, rule_id: int) -> RuleOut:
    return _to_out(get_rule(db, rule_id))



def update_rule(db: Session, rule_id: int, payload: RuleUpdate) -> RuleOut:
    rule = get_rule(db, rule_id)
    data = payload.model_dump(exclude_unset=True)
    if "value" in data:
        rule.value_json = data.pop("value")
    if "when" in data:
        when = data.pop("when")
        rule.when_json = when if isinstance(when, dict) else (when.model_dump() if when else None)
    for key, value in data.items():
        setattr(rule, key, value)
    rule.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


def delete_rule(db: Session, rule_id: int) -> None:
    rule = get_rule(db, rule_id)
    db.delete(rule)
    db.commit()


def set_enabled(db: Session, rule_id: int, enabled: bool) -> RuleOut:
    rule = get_rule(db, rule_id)
    rule.enabled = enabled
    rule.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


def load_reference_lookup(db: Session) -> dict[str, list[str]]:
    rows = db.scalars(select(ValidationReferenceSet)).all()
    return {row.set_code: [str(item) for item in (row.values_json or [])] for row in rows}


def replace_rule_runs(db: Session, batch_id: str) -> None:
    from app.modules.pipeline.preservation import protected_ids_for_replace

    protected = protected_ids_for_replace()
    runs = [
        run
        for run in db.scalars(
            select(ValidationRun).where(
                ValidationRun.batch_id == batch_id,
                ValidationRun.validation_type == "rules",
            )
        ).all()
        if run.id not in protected
    ]
    run_ids = [run.id for run in runs]
    if run_ids:
        violations = db.scalars(
            select(RuleViolation).where(RuleViolation.validation_run_id.in_(run_ids))
        ).all()
        for row in violations:
            db.delete(row)
        for run in runs:
            db.delete(run)
    db.commit()
