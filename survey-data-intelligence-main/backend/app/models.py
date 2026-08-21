from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db import Base


class BatchStatus:
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PROFILING = "PROFILING"
    PROFILED = "PROFILED"
    PROFILE_FAILED = "PROFILE_FAILED"


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(32))
    survey_code: Mapped[str] = mapped_column(String(64), default="DEMO")
    status: Mapped[str] = mapped_column(String(32), default=BatchStatus.RECEIVED)
    schema_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    records: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_count: Mapped[int | None] = mapped_column("columns", Integer, nullable=True)
    parquet_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class DatasetProfile(Base):
    __tablename__ = "dataset_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("batches.batch_id"), unique=True, index=True
    )
    record_count: Mapped[int] = mapped_column(Integer)
    column_count: Mapped[int] = mapped_column(Integer)
    numeric_column_count: Mapped[int] = mapped_column(Integer)
    categorical_column_count: Mapped[int] = mapped_column(Integer)
    missing_rate: Mapped[float] = mapped_column(Float)
    duplicate_count: Mapped[int] = mapped_column(Integer)
    parquet_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile_json: Mapped[dict] = mapped_column(JSON)
    profiled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class VariableProfile(Base):
    __tablename__ = "variable_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("batches.batch_id"), index=True
    )
    variable_name: Mapped[str] = mapped_column(String(256))
    dtype: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    profile_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RecordProfile(Base):
    __tablename__ = "record_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("batches.batch_id"), index=True
    )
    record_id: Mapped[str] = mapped_column(String(128), index=True)
    enumerator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    district_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    features_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EnumeratorProfile(Base):
    __tablename__ = "enumerator_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("batches.batch_id"), index=True
    )
    enumerator_id: Mapped[str] = mapped_column(String(128), index=True)
    record_count: Mapped[int] = mapped_column(Integer)
    profile_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ClusterProfile(Base):
    __tablename__ = "cluster_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("batches.batch_id"), index=True
    )
    cluster_id: Mapped[str] = mapped_column(String(128), index=True)
    district_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    record_count: Mapped[int] = mapped_column(Integer)
    profile_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DistrictProfile(Base):
    __tablename__ = "district_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("batches.batch_id"), index=True
    )
    district_id: Mapped[str] = mapped_column(String(128), index=True)
    record_count: Mapped[int] = mapped_column(Integer)
    profile_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HistoricalProfile(Base):
    __tablename__ = "historical_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("batches.batch_id"), index=True
    )
    schema_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    grain: Mapped[str] = mapped_column(String(64))
    grain_key: Mapped[str] = mapped_column(String(128))
    stats_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SirlAiEnrichment(Base):
    __tablename__ = "sirl_ai_enrichments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("batches.batch_id"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enrichment_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ValidationRule(Base):
    __tablename__ = "validation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    survey_code: Mapped[str] = mapped_column(String(64), default="DEMO")
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    field: Mapped[str] = mapped_column(String(128))
    operator: Mapped[str] = mapped_column(String(64))
    value_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    second_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    when_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    scope: Mapped[str] = mapped_column(String(32), default="RECORD")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ValidationReferenceSet(Base):
    __tablename__ = "validation_reference_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    values_json: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ValidationRun(Base):
    __tablename__ = "validation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("batches.batch_id"), index=True
    )
    validation_type: Mapped[str] = mapped_column(String(32), default="rules")
    status: Mapped[str] = mapped_column(String(32))
    rules_evaluated: Mapped[int] = mapped_column(Integer, default=0)
    records_checked: Mapped[int] = mapped_column(Integer, default=0)
    violation_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_rules_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RuleViolation(Base):
    __tablename__ = "rule_violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    validation_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("validation_runs.id"), index=True
    )
    batch_id: Mapped[str] = mapped_column(String(128), index=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("validation_rules.id"))
    rule_code: Mapped[str] = mapped_column(String(64))
    record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enumerator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    district_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    severity: Mapped[str] = mapped_column(String(16))
    field: Mapped[str] = mapped_column(String(128))
    observed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_condition: Mapped[str] = mapped_column(String(256))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StatisticalEvidence(Base):
    """Phase 5B statistical detections only. Not a risk score or rule violation."""

    __tablename__ = "statistical_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    validation_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("validation_runs.id"), index=True
    )
    batch_id: Mapped[str] = mapped_column(String(128), index=True)
    record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enumerator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    district_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    variable: Mapped[str] = mapped_column(String(128))
    detector: Mapped[str] = mapped_column(String(32))
    scope: Mapped[str] = mapped_column(String(32))
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_std: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[str] = mapped_column(String(16))
    evidence_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MlEvidence(Base):
    """Phase 5C Isolation Forest detections only. Not a risk score."""

    __tablename__ = "ml_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    validation_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("validation_runs.id"), index=True
    )
    batch_id: Mapped[str] = mapped_column(String(128), index=True)
    record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enumerator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    district_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_type: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(64))
    feature_names_json: Mapped[list] = mapped_column(JSON)
    anomaly_score: Mapped[float] = mapped_column(Float)
    raw_model_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    prediction: Mapped[str] = mapped_column(String(16))
    severity: Mapped[str] = mapped_column(String(16))
    training_source: Mapped[str] = mapped_column(String(32))
    training_records: Mapped[int] = mapped_column(Integer)
    evidence_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UnifiedRiskAssessment(Base):
    """Phase 6 fused interpretation. Does not replace source evidence."""

    __tablename__ = "unified_risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    validation_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("validation_runs.id"), index=True
    )
    batch_id: Mapped[str] = mapped_column(String(128), index=True)
    record_id: Mapped[str] = mapped_column(String(128), index=True)
    enumerator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    district_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    risk_score: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    agreement: Mapped[str] = mapped_column(String(32))
    available_sources_json: Mapped[list] = mapped_column(JSON)
    missing_sources_json: Mapped[list] = mapped_column(JSON)
    source_scores_json: Mapped[dict] = mapped_column(JSON)
    source_severities_json: Mapped[dict] = mapped_column(JSON)
    escalation_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    methodology_version: Mapped[str] = mapped_column(String(64))
    evidence_refs_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    anomaly_status: Mapped[str] = mapped_column(String(16), default="NORMAL")
    classification_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intelligence_classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    primary_detector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detector_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UnifiedDatasetAssessment(Base):
    """Phase 6 dataset-level statistical context. Not a record risk score."""

    __tablename__ = "unified_dataset_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    validation_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("validation_runs.id"), unique=True, index=True
    )
    batch_id: Mapped[str] = mapped_column(String(128), index=True)
    context_score: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(16))
    evidence_confidence: Mapped[float] = mapped_column(Float)
    agreement: Mapped[str] = mapped_column(String(32), default="single_source")
    statistical_evidence_ids_json: Mapped[list] = mapped_column(JSON)
    methodology_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AiExplanation(Base):
    """Phase 7 AI explanation of Phase 6 assessments. Not a source of truth."""

    __tablename__ = "ai_explanations"
    __table_args__ = (
        UniqueConstraint("batch_id", "record_id", name="uq_ai_explanations_batch_record"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(128), index=True)
    record_id: Mapped[str] = mapped_column(String(128), index=True)
    validation_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("validation_runs.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    explanation_json: Mapped[dict] = mapped_column(JSON)
    context_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PipelineRun(Base):
    """Orchestration lifecycle only. Does not store engine scores."""

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    current_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=False, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PipelineStageRun(Base):
    __tablename__ = "pipeline_stage_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pipeline_runs.id"), index=True
    )
    stage: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(128), default="")
    district_scope_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cluster_scope_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Investigation(Base):
    """Human decision layer. Does not alter Phase 6 risk assessments."""

    __tablename__ = "investigations"
    __table_args__ = (UniqueConstraint("batch_id", "record_id", name="uq_investigation_record"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(128), index=True)
    record_id: Mapped[str] = mapped_column(String(128), index=True)
    validation_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="OPEN")
    priority: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    supervisor_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    finding: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_taken: Mapped[str | None] = mapped_column(String(64), nullable=True)
    final_classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    enumerator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    district_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InvestigationAuditLog(Base):
    __tablename__ = "investigation_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("investigations.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DetectorConfig(Base):
    """Enable/disable intelligence detectors. Thresholds stay JSON-based."""

    __tablename__ = "detector_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    detector_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    category: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    thresholds_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class QualityDetection(Base):
    """Multi-layer quality signal. Not a Phase 6 risk score and not a fraud label."""

    __tablename__ = "quality_detections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    validation_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("validation_runs.id"), index=True
    )
    batch_id: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(128), index=True)
    record_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    enumerator_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    cluster_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    district_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    household_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detector_type: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    classification: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    field_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    deviation: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    explanation: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


