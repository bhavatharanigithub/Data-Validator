from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Batch, BatchStatus, RecordProfile, UnifiedRiskAssessment, ValidationRun
from app.modules.ai.errors import AIUnavailableError
from app.modules.ai.factory import build_ai_provider
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.sirl.profiler import RECORD_ID_CANDIDATES, _first_present
from app.modules.storage.parquet import ParquetStorage
from app.modules.validation.errors import ValidationError
from app.modules.validation.explanation.prompts import SYSTEM_PROMPT
from app.modules.validation.explanation.repository import get_explanation, to_block, upsert_explanation
from app.modules.validation.explanation.schemas import (
    ExplanationBatchResponse,
    ExplanationBlock,
    ExplanationPayload,
    ExplanationRecordResponse,
    ExplanationRunRequest,
    RiskAssessmentSlice,
    normalize_model_explanation,
)
from app.modules.validation.explanation.selector import (
    context_hash,
    has_usable_evidence,
    select_clean_context,
    select_explanation_context,
)
from app.modules.validation.fusion.classification import (
    classify_assessment,
    hydrate_assessment_rule_codes,
    should_auto_explain,
)

_INGESTED = {BatchStatus.COMPLETED, BatchStatus.PROFILED}
_SEVERITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NONE": 4}
_STRIP_KEYS = {
    "anomaly_status",
    "classification_reason",
    "risk_score",
    "severity",
    "evidence_confidence",
    "agreement",
    "escalation_applied",
}


@dataclass(frozen=True)
class ExplanationSubject:
    batch_id: str
    record_id: str
    assessment: UnifiedRiskAssessment | None

    @property
    def severity(self) -> str:
        if self.assessment is None:
            return "NONE"
        return self.assessment.severity

    @property
    def risk_score(self) -> float:
        if self.assessment is None:
            return -1.0
        return float(self.assessment.risk_score)


def _require_batch(db: Session, batch_id: str) -> Batch:
    batch = db.scalars(select(Batch).where(Batch.batch_id == batch_id)).first()
    if batch is None:
        raise ValidationError("batch not found", status_code=404)
    if batch.status not in _INGESTED:
        raise ValidationError("batch ingestion is not COMPLETED", status_code=409)
    return batch


def _latest_fusion_run(db: Session, batch_id: str) -> ValidationRun:
    run = db.scalars(
        select(ValidationRun)
        .where(
            ValidationRun.batch_id == batch_id,
            ValidationRun.validation_type == "fusion",
            ValidationRun.status == "COMPLETED",
        )
        .order_by(ValidationRun.id.desc())
    ).first()
    if run is None:
        raise ValidationError("fusion assessment not found for batch", status_code=409)
    return run


def _assessments(db: Session, fusion_run_id: int) -> list[UnifiedRiskAssessment]:
    rows = list(
        db.scalars(
            select(UnifiedRiskAssessment).where(
                UnifiedRiskAssessment.validation_run_id == fusion_run_id
            )
        ).all()
    )
    hydrate_assessment_rule_codes(db, rows)
    return rows


def _parquet_record_ids(batch_id: str) -> list[str]:
    store = ParquetStorage()
    if not store.exists(batch_id):
        return []
    try:
        import pyarrow.parquet as pq

        path = store.absolute_path(batch_id)
        names = pq.read_schema(path).names
        column = _first_present(list(names), RECORD_ID_CANDIDATES)
        if column is None:
            return []
        values = pq.read_table(path, columns=[column]).column(column).to_pylist()
        return [str(item) for item in values if item is not None]
    except Exception:
        return []


def list_batch_record_ids(db: Session, batch_id: str) -> list[str]:
    profile_ids = list(
        db.scalars(select(RecordProfile.record_id).where(RecordProfile.batch_id == batch_id)).all()
    )
    if profile_ids:
        return [str(item) for item in profile_ids]
    return _parquet_record_ids(batch_id)


def assessment_slice(row: UnifiedRiskAssessment | None) -> RiskAssessmentSlice:
    if row is None:
        return RiskAssessmentSlice(
            risk_score=None,
            severity=None,
            evidence_confidence=None,
            agreement=None,
            available_sources=[],
            missing_sources=["rules", "statistics", "ml"],
            anomaly_status="NORMAL",
            phase6_assessment_available=False,
        )
    classified = classify_assessment(row)
    return RiskAssessmentSlice(
        risk_score=row.risk_score,
        severity=row.severity,
        evidence_confidence=row.confidence,
        agreement=row.agreement,
        escalation_applied=bool(row.escalation_applied),
        escalation_reason=row.escalation_reason,
        available_sources=list(row.available_sources_json or []),
        missing_sources=list(row.missing_sources_json or []),
        methodology_version=row.methodology_version,
        anomaly_status=classified["anomaly_status"],
        classification_reason=classified["classification_reason"],
        phase6_assessment_available=True,
    )


def _record_response(
    batch_id: str,
    record_id: str,
    assessment: UnifiedRiskAssessment | None,
    explanation_row,
) -> ExplanationRecordResponse:
    return ExplanationRecordResponse(
        record_id=record_id,
        batch_id=batch_id,
        risk_assessment=assessment_slice(assessment),
        explanation=to_block(explanation_row),
    )


def filter_assessments(
    rows: list[UnifiedRiskAssessment],
    request: ExplanationRunRequest | None,
    default_limit: int,
) -> tuple[list[UnifiedRiskAssessment], int, int]:
    payload = request or ExplanationRunRequest()
    subjects = [
        ExplanationSubject(getattr(row, "batch_id", ""), row.record_id, row) for row in rows
    ]
    selected, limit, skipped = filter_subjects(subjects, payload, default_limit)
    return [item.assessment for item in selected if item.assessment is not None], limit, skipped


def filter_subjects(
    rows: list[ExplanationSubject],
    request: ExplanationRunRequest | None,
    default_limit: int,
) -> tuple[list[ExplanationSubject], int, int]:
    payload = request or ExplanationRunRequest()
    limit = payload.limit if payload.limit is not None else default_limit
    limit = max(1, min(int(limit), 200))
    filtered = list(rows)
    if payload.severity:
        filtered = [row for row in filtered if row.severity == payload.severity]
    elif payload.scope == "detected":
        filtered = [row for row in filtered if should_auto_explain(row.assessment)]
    elif payload.scope != "all" and payload.min_risk_score is None:
        filtered = [row for row in filtered if row.severity in {"HIGH", "CRITICAL"}]
    if payload.min_risk_score is not None:
        filtered = [
            row
            for row in filtered
            if row.assessment is not None and row.risk_score >= float(payload.min_risk_score)
        ]
        if payload.scope != "all":
            filtered = [
                row
                for row in filtered
                if row.assessment is None or should_auto_explain(row.assessment)
            ]
    filtered.sort(
        key=lambda row: (
            _SEVERITY_RANK.get(row.severity, 9),
            -float(row.risk_score),
            row.record_id,
        )
    )
    skipped = max(0, len(filtered) - limit)
    return filtered[:limit], limit, skipped


def _concurrency() -> int:
    return max(1, min(int(settings.ai_explanation_concurrency), 8))


def explain_assessment(
    db: Session,
    assessment: UnifiedRiskAssessment,
    provider=None,
) -> ExplanationRecordResponse:
    return explain_subject(
        db,
        ExplanationSubject(assessment.batch_id, assessment.record_id, assessment),
        provider=provider,
        fusion_run_id=assessment.validation_run_id,
    )


def explain_subject(
    db: Session,
    subject: ExplanationSubject,
    provider=None,
    fusion_run_id: int | None = None,
    force: bool = False,
) -> ExplanationRecordResponse:
    started = time.perf_counter()
    assessment = subject.assessment
    if assessment is not None:
        context = select_explanation_context(
            db, assessment, max_bytes=int(settings.ai_explanation_max_context_bytes)
        )
        run_id = assessment.validation_run_id
    else:
        context = select_clean_context(subject.batch_id, subject.record_id)
        run_id = int(fusion_run_id or 0)
        if run_id <= 0:
            raise ValidationError("fusion assessment not found for batch", status_code=409)
    hashed = context_hash(context)
    if assessment is not None and not should_auto_explain(assessment):
        return _record_response(subject.batch_id, subject.record_id, assessment, None)
    existing = get_explanation(db, subject.batch_id, subject.record_id)
    cached_available = (
        existing is not None
        and existing.status == "available"
        and existing.context_hash == hashed
        and existing.validation_run_id == run_id
    )
    if cached_available and not force:
        log_event(
            "explanation_cache_hit",
            batch_id=subject.batch_id,
            record_id=subject.record_id,
            provider_status="cache_hit",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return _record_response(subject.batch_id, subject.record_id, assessment, existing)

    preserve_available = bool(force and existing is not None and existing.status == "available")
    if not preserve_available:
        upsert_explanation(
            db,
            batch_id=subject.batch_id,
            record_id=subject.record_id,
            validation_run_id=run_id,
            status="generating",
            reason=None,
            model=None,
            payload=None,
            context_hash=hashed,
        )
    active = provider if provider is not None else build_ai_provider()
    if active is None:
        return _generation_failed(
            db,
            subject=subject,
            assessment=assessment,
            run_id=run_id,
            hashed=hashed,
            reason="not_configured",
            model=None,
            started=started,
            preserve_available=preserve_available,
            existing=existing,
        )

    try:
        raw = active.complete_json(
            system=SYSTEM_PROMPT,
            user=json.dumps(context, default=str),
        )
        raw = normalize_model_explanation(raw)
        raw = {key: value for key, value in raw.items() if key not in _STRIP_KEYS}
        payload = ExplanationPayload.model_validate(raw)
        row = upsert_explanation(
            db,
            batch_id=subject.batch_id,
            record_id=subject.record_id,
            validation_run_id=run_id,
            status="available",
            reason=None,
            model=getattr(active, "model", None),
            payload=payload,
            context_hash=hashed,
        )
        log_event(
            "explanation_available",
            batch_id=subject.batch_id,
            record_id=subject.record_id,
            provider_status="success",
            latency_ms=int((time.perf_counter() - started) * 1000),
            evidence_present=has_usable_evidence(context),
        )
        return _record_response(subject.batch_id, subject.record_id, assessment, row)
    except AIUnavailableError as exc:
        return _generation_failed(
            db,
            subject=subject,
            assessment=assessment,
            run_id=run_id,
            hashed=hashed,
            reason=exc.reason,
            model=getattr(active, "model", None),
            started=started,
            preserve_available=preserve_available,
            existing=existing,
        )
    except PydanticValidationError as exc:
        field_names = [
            ".".join(str(part) for part in error.get("loc") or ())
            for error in exc.errors()[:8]
        ]
        error_types = [str(error.get("type") or "") for error in exc.errors()[:8]]
        return _generation_failed(
            db,
            subject=subject,
            assessment=assessment,
            run_id=run_id,
            hashed=hashed,
            reason="invalid_response",
            model=getattr(active, "model", None),
            started=started,
            preserve_available=preserve_available,
            existing=existing,
            validation_fields=field_names,
            validation_types=error_types,
        )
    except Exception:
        return _generation_failed(
            db,
            subject=subject,
            assessment=assessment,
            run_id=run_id,
            hashed=hashed,
            reason="provider_error",
            model=getattr(active, "model", None),
            started=started,
            preserve_available=preserve_available,
            existing=existing,
        )


def _generation_failed(
    db: Session,
    *,
    subject: ExplanationSubject,
    assessment,
    run_id: int,
    hashed: str,
    reason: str,
    model: str | None,
    started: float,
    preserve_available: bool,
    existing,
    validation_fields: list[str] | None = None,
    validation_types: list[str] | None = None,
) -> ExplanationRecordResponse:
    extra: dict[str, object] = {}
    if validation_fields is not None:
        extra["validation_fields"] = validation_fields
    if validation_types is not None:
        extra["validation_types"] = validation_types
    log_failure(
        "explanation_unavailable",
        batch_id=subject.batch_id,
        record_id=subject.record_id,
        provider_status=reason,
        latency_ms=int((time.perf_counter() - started) * 1000),
        **extra,
    )
    if preserve_available and existing is not None:
        return ExplanationRecordResponse(
            record_id=subject.record_id,
            batch_id=subject.batch_id,
            risk_assessment=assessment_slice(assessment),
            explanation=ExplanationBlock(status="unavailable", reason=reason, model=model),
        )
    row = upsert_explanation(
        db,
        batch_id=subject.batch_id,
        record_id=subject.record_id,
        validation_run_id=run_id,
        status="unavailable",
        reason=reason,
        model=model,
        payload=None,
        context_hash=hashed,
    )
    return _record_response(subject.batch_id, subject.record_id, assessment, row)


def _load_subject(db: Session, batch_id: str, record_id: str, fusion: ValidationRun) -> ExplanationSubject:
    assessment = db.scalars(
        select(UnifiedRiskAssessment).where(
            UnifiedRiskAssessment.validation_run_id == fusion.id,
            UnifiedRiskAssessment.record_id == record_id,
        )
    ).first()
    if assessment is not None:
        hydrate_assessment_rule_codes(db, [assessment])
        return ExplanationSubject(batch_id, record_id, assessment)
    known = list_batch_record_ids(db, batch_id)
    if record_id not in known and known:
        raise ValidationError("unified assessment not found for record", status_code=404)
    if assessment is None and not known:
        raise ValidationError("unified assessment not found for record", status_code=404)
    return ExplanationSubject(batch_id, record_id, None)


def explain_record(
    db: Session,
    batch_id: str,
    record_id: str,
    provider=None,
    force: bool = False,
) -> ExplanationRecordResponse:
    _require_batch(db, batch_id)
    fusion = _latest_fusion_run(db, batch_id)
    subject = _load_subject(db, batch_id, record_id, fusion)
    return explain_subject(db, subject, provider=provider, fusion_run_id=fusion.id, force=force)


def _explain_job(
    batch_id: str,
    record_id: str,
    fusion_run_id: int,
    provider=None,
) -> ExplanationRecordResponse:
    db = SessionLocal()
    try:
        assessment = db.scalars(
            select(UnifiedRiskAssessment).where(
                UnifiedRiskAssessment.validation_run_id == fusion_run_id,
                UnifiedRiskAssessment.record_id == record_id,
            )
        ).first()
        if assessment is not None:
            hydrate_assessment_rule_codes(db, [assessment])
        subject = ExplanationSubject(batch_id, record_id, assessment)
        return explain_subject(db, subject, provider=provider, fusion_run_id=fusion_run_id)
    finally:
        db.close()


def explain_batch(
    db: Session,
    batch_id: str,
    provider=None,
    request: ExplanationRunRequest | None = None,
) -> ExplanationBatchResponse:
    _require_batch(db, batch_id)
    fusion = _latest_fusion_run(db, batch_id)
    rows = _assessments(db, fusion.id)
    payload = request or ExplanationRunRequest()
    default_limit = (
        int(settings.ai_explanation_all_limit)
        if payload.scope in {"all", "detected"}
        else int(settings.ai_explanation_batch_limit)
    )
    if payload.scope == "all":
        assessed = {row.record_id: row for row in rows}
        ids = list(assessed)
        extra = list_batch_record_ids(db, batch_id)
        ids = sorted(set(ids) | set(extra))
        subjects = [
            ExplanationSubject(batch_id, record_id, assessed.get(record_id)) for record_id in ids
        ]
        if not subjects:
            raise ValidationError("insufficient_evidence", status_code=409)
        selected, limit, skipped = filter_subjects(subjects, payload, default_limit)
    else:
        if not rows:
            if payload.scope == "detected":
                return ExplanationBatchResponse(
                    success=True,
                    batch_id=batch_id,
                    fusion_run_id=fusion.id,
                    records_explained=0,
                    available=0,
                    unavailable=0,
                    cached=0,
                    skipped=0,
                    limit=default_limit,
                    min_risk_score=payload.min_risk_score,
                    severity=payload.severity,
                    scope=payload.scope,
                    items=[],
                )
            raise ValidationError("insufficient_evidence", status_code=409)
        selected_rows, limit, skipped = filter_assessments(rows, payload, default_limit=default_limit)
        selected = [ExplanationSubject(row.batch_id, row.record_id, row) for row in selected_rows]

    priors = {item.record_id: get_explanation(db, batch_id, item.record_id) for item in selected}
    workers = _concurrency()
    items: list[ExplanationRecordResponse] = []
    if workers == 1 or len(selected) <= 1:
        for subject in selected:
            items.append(explain_subject(db, subject, provider=provider, fusion_run_id=fusion.id))
    else:
        ordered: dict[str, ExplanationRecordResponse] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_explain_job, subject.batch_id, subject.record_id, fusion.id, provider): subject.record_id
                for subject in selected
            }
            for future in as_completed(futures):
                record_id = futures[future]
                ordered[record_id] = future.result()
        items = [ordered[subject.record_id] for subject in selected]

    cached = 0
    for subject, item in zip(selected, items, strict=True):
        prior = priors.get(subject.record_id)
        if (
            prior is not None
            and prior.status == "available"
            and item.explanation.status == "available"
            and prior.updated_at == item.explanation.updated_at
        ):
            cached += 1
    available = sum(1 for item in items if item.explanation.status == "available")
    return ExplanationBatchResponse(
        success=True,
        batch_id=batch_id,
        fusion_run_id=fusion.id,
        records_explained=len(items),
        available=available,
        unavailable=len(items) - available,
        cached=cached,
        skipped=skipped,
        limit=limit,
        min_risk_score=payload.min_risk_score,
        severity=payload.severity,
        scope=payload.scope,
        items=items,
    )


def get_record_explanation(db: Session, batch_id: str, record_id: str) -> ExplanationRecordResponse:
    _require_batch(db, batch_id)
    fusion = _latest_fusion_run(db, batch_id)
    subject = _load_subject(db, batch_id, record_id, fusion)
    row = get_explanation(db, batch_id, record_id)
    if row is None:
        raise ValidationError("explanation not found", status_code=404)
    return _record_response(batch_id, record_id, subject.assessment, row)
