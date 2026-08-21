from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ValidationReferenceSet, ValidationRule
from app.modules.validation.rules.schemas import PredicateIn, RuleCreate


SAMPLE_RULES = [
    RuleCreate(
        rule_code="AGE_MIN",
        name="Minimum age",
        description="Age must be at least 0.",
        field="age",
        operator="greater_than_or_equal",
        value=0,
        severity="HIGH",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="AGE_MAX",
        name="Maximum age",
        description="Age must be at most 100.",
        field="age",
        operator="less_than_or_equal",
        value=100,
        severity="HIGH",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="WORKING_HOURS_MIN",
        name="Minimum working hours",
        description="Working hours must be at least 0.",
        field="working_hours",
        operator="greater_than_or_equal",
        value=0,
        severity="HIGH",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="WORKING_HOURS_MAX",
        name="Maximum working hours",
        description="Working hours must be at most 168 (hours in a week).",
        field="working_hours",
        operator="less_than_or_equal",
        value=168,
        severity="CRITICAL",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="INCOME_NON_NEGATIVE",
        name="Non-negative income",
        description="Income must be at least 0.",
        field="income",
        operator="greater_than_or_equal",
        value=0,
        severity="HIGH",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="HOUSEHOLD_SIZE_MIN",
        name="Household size minimum",
        description="Household size must be at least 1 when the field is present.",
        field="household_size",
        operator="greater_than_or_equal",
        value=1,
        severity="HIGH",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="RESPONDENT_ID_REQUIRED",
        name="Respondent identifier required",
        description="Respondent identifier must exist.",
        field="respondent_id",
        operator="is_not_blank",
        severity="CRITICAL",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="ENUMERATOR_REQUIRED",
        name="Enumerator required",
        description="Enumerator identifier must exist.",
        field="enumerator_id",
        operator="is_not_blank",
        severity="HIGH",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="CLUSTER_REQUIRED",
        name="Cluster required",
        description="Cluster identifier must exist.",
        field="cluster_id",
        operator="is_not_blank",
        severity="HIGH",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="DISTRICT_REQUIRED",
        name="District required",
        description="District code must exist.",
        field="district_code",
        operator="is_not_blank",
        severity="HIGH",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="EMPLOYED_HAS_HOURS",
        name="Employed records must have hours",
        description="If employment_status is employed, working_hours must be greater than 0.",
        field="working_hours",
        operator="greater_than",
        value=0,
        when=PredicateIn(field="employment_status", operator="equals", value="employed"),
        severity="MEDIUM",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="UNEMPLOYED_ZERO_HOURS",
        name="Unemployed records should have zero hours",
        description="If employment_status is unemployed, working_hours should be 0.",
        field="working_hours",
        operator="equals",
        value=0,
        when=PredicateIn(field="employment_status", operator="equals", value="unemployed"),
        severity="MEDIUM",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="CLUSTER_IN_REFERENCE",
        name="Cluster in reference set",
        description="cluster_id must be in the sample cluster list.",
        field="cluster_id",
        operator="in_reference",
        value="clusters",
        severity="MEDIUM",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="DISTRICT_IN_REFERENCE",
        name="District in reference set",
        description="district_code must be in the sample district list.",
        field="district_code",
        operator="in_reference",
        value="districts",
        severity="MEDIUM",
        is_sample=True,
        created_by="sample",
    ),
    RuleCreate(
        rule_code="ENUMERATOR_IN_REFERENCE",
        name="Enumerator in reference set",
        description="enumerator_id must be in the sample enumerator list.",
        field="enumerator_id",
        operator="in_reference",
        value="enumerators",
        severity="MEDIUM",
        is_sample=True,
        created_by="sample",
    ),
]


SAMPLE_REFERENCES = {
    "clusters": ["C01", "C02"],
    "districts": ["1101", "1102"],
    "enumerators": ["E12", "E15"],
}

# Test leftovers persisted into a shared demo DB (e.g. age == 34) and must not stay enabled.
_EPHEMERAL_PREFIXES = (
    "TEST_AGE_EQ_",
    "MISSING_COL",
    "UNK_REF_",
    "SURVEY_A_ONLY_",
    "SURVEY_B_ONLY_",
    "BAD_SEV",
    "BAD_CROSS",
    "BAD_OP",
)


def _is_ephemeral_rule_code(rule_code: str) -> bool:
    return any(rule_code.startswith(prefix) for prefix in _EPHEMERAL_PREFIXES)


def _apply_sample_rule(row: ValidationRule, payload: RuleCreate) -> None:
    row.survey_code = payload.survey_code
    row.name = payload.name
    row.description = payload.description
    row.field = payload.field
    row.operator = payload.operator
    row.value_json = payload.value
    row.second_field = payload.second_field
    row.when_json = payload.when.model_dump() if payload.when else None
    row.severity = payload.severity
    row.scope = payload.scope
    row.is_sample = True
    row.created_by = "sample"


def seed_sample_validation(db: Session) -> None:
    existing = {row.rule_code: row for row in db.scalars(select(ValidationRule)).all()}
    for payload in SAMPLE_RULES:
        current = existing.get(payload.rule_code)
        if current is None:
            when = payload.when.model_dump() if payload.when else None
            db.add(
                ValidationRule(
                    rule_code=payload.rule_code,
                    survey_code=payload.survey_code,
                    name=payload.name,
                    description=payload.description,
                    field=payload.field,
                    operator=payload.operator,
                    value_json=payload.value,
                    second_field=payload.second_field,
                    when_json=when,
                    severity=payload.severity,
                    scope=payload.scope,
                    enabled=payload.enabled,
                    is_sample=True,
                    created_by="sample",
                )
            )
            continue
        _apply_sample_rule(current, payload)
        if payload.rule_code in {
            "RESPONDENT_ID_REQUIRED",
            "ENUMERATOR_REQUIRED",
            "CLUSTER_REQUIRED",
            "DISTRICT_REQUIRED",
        } and current.operator == "is_not_null":
            current.operator = "is_not_blank"
    for row in existing.values():
        if row.enabled and (not row.is_sample) and _is_ephemeral_rule_code(row.rule_code):
            row.enabled = False
    existing_sets = {
        row.set_code for row in db.scalars(select(ValidationReferenceSet)).all()
    }
    for code, values in SAMPLE_REFERENCES.items():
        if code in existing_sets:
            continue
        db.add(
            ValidationReferenceSet(
                set_code=code,
                description=f"Demonstration {code} reference values from sample survey data.",
                values_json=values,
            )
        )
    db.commit()
