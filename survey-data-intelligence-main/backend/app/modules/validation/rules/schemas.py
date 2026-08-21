from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.validation.rules.operators import ALLOWED_OPERATORS, CROSS_FIELD_OPERATORS

SEVERITIES = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})


class PredicateIn(BaseModel):
    field: str
    operator: str
    value: Any = None
    second_field: str | None = None

    @field_validator("operator")
    @classmethod
    def _operator_allowed(cls, value: str) -> str:
        if value not in ALLOWED_OPERATORS:
            raise ValueError(f"unsupported operator: {value}")
        return value


class RuleCreate(BaseModel):
    rule_code: str
    survey_code: str = "DEMO"
    name: str
    description: str | None = None
    field: str
    operator: str
    value: Any = None
    second_field: str | None = None
    when: PredicateIn | None = None
    severity: str = "MEDIUM"
    scope: str = "RECORD"
    enabled: bool = True
    is_sample: bool = False
    created_by: str | None = "api"

    @field_validator("operator")
    @classmethod
    def _operator_allowed(cls, value: str) -> str:
        if value not in ALLOWED_OPERATORS:
            raise ValueError(f"unsupported operator: {value}")
        return value

    @field_validator("severity")
    @classmethod
    def _severity_allowed(cls, value: str) -> str:
        severity = value.upper()
        if severity not in SEVERITIES:
            raise ValueError("severity must be LOW, MEDIUM, HIGH, or CRITICAL")
        return severity

    @model_validator(mode="after")
    def _cross_field(self) -> "RuleCreate":
        if self.operator in CROSS_FIELD_OPERATORS and not self.second_field:
            raise ValueError("second_field is required for cross-field operators")
        return self


class RuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    field: str | None = None
    operator: str | None = None
    value: Any = None
    second_field: str | None = None
    when: PredicateIn | None = None
    severity: str | None = None
    scope: str | None = None
    enabled: bool | None = None

    @field_validator("operator")
    @classmethod
    def _operator_allowed(cls, value: str | None) -> str | None:
        if value is not None and value not in ALLOWED_OPERATORS:
            raise ValueError(f"unsupported operator: {value}")
        return value

    @field_validator("severity")
    @classmethod
    def _severity_allowed(cls, value: str | None) -> str | None:
        if value is None:
            return value
        severity = value.upper()
        if severity not in SEVERITIES:
            raise ValueError("severity must be LOW, MEDIUM, HIGH, or CRITICAL")
        return severity


class RuleOut(BaseModel):
    id: int
    rule_code: str
    survey_code: str
    name: str
    description: str | None
    field: str
    operator: str
    value: Any = None
    second_field: str | None
    when: dict[str, Any] | None = None
    severity: str
    scope: str
    enabled: bool
    version: int
    is_sample: bool
    created_by: str | None


class ViolationOut(BaseModel):
    record_id: str | None
    rule_code: str
    severity: str
    field: str
    observed_value: str | None
    expected_condition: str
    message: str
    enumerator_id: str | None = None
    cluster_id: str | None = None
    district_id: str | None = None


class ValidationRunResponse(BaseModel):
    success: bool
    batch_id: str
    validation_run_id: int
    engine: Literal["rules"] = "rules"
    rules_evaluated: int
    records_checked: int
    violations: int
    high_severity: int = 0
    medium_severity: int = 0
    low_severity: int = 0
    critical_severity: int = 0
    skipped_rules: list[dict[str, str]] = Field(default_factory=list)


class ValidationRunDetail(ValidationRunResponse):
    items: list[ViolationOut] = Field(default_factory=list)
