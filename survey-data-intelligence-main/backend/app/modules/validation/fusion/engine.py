from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Batch,
    BatchStatus,
    MlEvidence,
    RuleViolation,
    StatisticalEvidence,
    ValidationRun,
)
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.sirl.profiler import detect_roles
from app.modules.storage.parquet import ParquetStorage
from app.modules.validation.errors import ValidationError
from app.modules.validation.fusion.classification import (
    classification_debug_row,
    classify_anomaly_status,
    classify_intelligence,
    format_classification_table,
)
from app.modules.validation.fusion.repository import (
    persist_assessments,
    persist_dataset_assessment,
    replace_fusion_runs,
)
from app.modules.validation.fusion.schemas import FusionRunResponse
from app.modules.validation.intelligence.repository import list_detections
from app.modules.validation.fusion.scoring import (
    HIGH_SEVERITIES,
    SOURCES,
    aggregate_scores,
    fuse_dataset_context,
    fuse_record,
    load_fusion_settings,
    normalize_ml_score,
    normalize_rule_severity,
    normalize_stat_severity,
    strongest_severity,
)

_INGESTED = {BatchStatus.COMPLETED, BatchStatus.PROFILED}
_USABLE_RUN = {"COMPLETED"}


def _require_batch(db: Session, batch_id: str) -> Batch:
    batch = db.scalars(select(Batch).where(Batch.batch_id == batch_id)).first()
    if batch is None:
        raise ValidationError("batch not found", status_code=404)
    if batch.status not in _INGESTED:
        raise ValidationError("batch ingestion is not COMPLETED", status_code=409)
    return batch


def _latest_run(db: Session, batch_id: str, validation_type: str) -> ValidationRun | None:
    return db.scalars(
        select(ValidationRun)
        .where(
            ValidationRun.batch_id == batch_id,
            ValidationRun.validation_type == validation_type,
        )
        .order_by(ValidationRun.id.desc())
    ).first()


def _source_available(run: ValidationRun | None) -> bool:
    if run is None:
        return False
    return run.status in _USABLE_RUN


def _historical_context(stats_run: ValidationRun | None, ml_rows: list[MlEvidence]) -> bool:
    if stats_run is not None and isinstance(stats_run.skipped_rules_json, dict):
        if stats_run.skipped_rules_json.get("historical_context_available"):
            return True
    return any(row.training_source == "historical" for row in ml_rows)


def _cell(row, column: str | None) -> str | None:
    if not column:
        return None
    value = row.get(column)
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "nan", "None", "<NA>"}:
        return None
    return text


def _parquet_records(batch_id: str) -> list[dict]:
    store = ParquetStorage()
    if not store.exists(batch_id):
        return []
    try:
        frame = store.read(batch_id)
    except Exception:
        return []
    roles = detect_roles(frame)
    if not roles.record_id or roles.record_id not in frame.columns:
        return []
    rows = []
    for _, item in frame.iterrows():
        record_id = _cell(item, roles.record_id)
        if not record_id:
            continue
        rows.append(
            {
                "record_id": record_id,
                "enumerator_id": _cell(item, roles.enumerator_id),
                "cluster_id": _cell(item, roles.cluster_id),
                "district_id": _cell(item, roles.district_id),
            }
        )
    return rows


def _classify_bucket(available: list[str], bucket: dict, cfg, historical: bool) -> dict:
    rule_scores = [normalize_rule_severity(item.severity) for item in bucket["rules"]]
    stat_scores = [normalize_stat_severity(item.severity) for item in bucket["statistics"]]
    ml_scores = [normalize_ml_score(item.anomaly_score) for item in bucket["ml"]]
    source_scores: dict[str, float] = {}
    source_severities: dict[str, str] = {}
    if "rules" in available:
        source_scores["rules"] = aggregate_scores(rule_scores, cfg.remainder)
        source_severities["rules"] = strongest_severity(
            [item.severity for item in bucket["rules"]] or ["NONE"]
        )
    if "statistics" in available:
        source_scores["statistics"] = aggregate_scores(stat_scores, cfg.remainder)
        source_severities["statistics"] = strongest_severity(
            [item.severity for item in bucket["statistics"]] or ["NONE"]
        )
    if "ml" in available:
        source_scores["ml"] = aggregate_scores(ml_scores, cfg.remainder) if ml_scores else 0.0
        source_severities["ml"] = strongest_severity(
            [item.severity for item in bucket["ml"]] or ["NONE"]
        )
    fused = fuse_record(
        available=available,
        source_scores=source_scores,
        source_severities=source_severities,
        cfg=cfg,
        historical_context=historical,
    )
    refs = {
        "rule_violation_ids": [item.id for item in bucket["rules"]],
        "rule_codes": [item.rule_code for item in bucket["rules"]],
        "statistical_evidence_ids": [item.id for item in bucket["statistics"]],
        "ml_evidence_ids": [item.id for item in bucket["ml"]],
        "high_stat_variables": sorted(
            {
                str(item.variable)
                for item in bucket["statistics"]
                if item.variable and str(item.severity or "").upper() in HIGH_SEVERITIES
            }
        ),
    }
    classified = classify_anomaly_status(
        source_scores=source_scores,
        source_severities=source_severities,
        evidence_refs=refs,
    )
    intel = classify_intelligence(
        anomaly_status=classified["anomaly_status"],
        detector_types=list(refs.get("detectors") or []),
    )
    fused.update(
        {
            "anomaly_status": classified["anomaly_status"],
            "classification_reason": classified["classification_reason"],
            "intelligence_classification": intel["intelligence_classification"],
            "primary_detector": intel["primary_detector"],
            "detector_count": intel["detector_count"],
            "review_required": intel["review_required"],
            "evidence_refs": refs,
            "classification_debug": classification_debug_row(
                record_id="",
                fused=fused,
                classified=classified,
                evidence_refs=refs,
            ),
        }
    )
    return fused


def run_fusion(db: Session, batch_id: str) -> FusionRunResponse:
    _require_batch(db, batch_id)
    log_event("fusion_started", batch_id=batch_id)
    replace_fusion_runs(db, batch_id)
    run = ValidationRun(
        batch_id=batch_id,
        validation_type="fusion",
        status="RUNNING",
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        cfg = load_fusion_settings()
        rules_run = _latest_run(db, batch_id, "rules")
        stats_run = _latest_run(db, batch_id, "statistics")
        ml_run = _latest_run(db, batch_id, "ml")
        available = []
        if _source_available(rules_run):
            available.append("rules")
        if _source_available(stats_run):
            available.append("statistics")
        if _source_available(ml_run):
            available.append("ml")
        missing = [name for name in SOURCES if name not in available]

        if not available:
            run.status = "insufficient"
            run.records_checked = 0
            run.violation_count = 0
            run.skipped_rules_json = {
                "engine": "fusion",
                "status": "insufficient",
                "available_sources": [],
                "missing_sources": list(SOURCES),
                "methodology_version": cfg.methodology_version,
                "weights": cfg.weights,
            }
            run.completed_at = datetime.now(UTC)
            db.commit()
            return _summary(run, [])

        rule_rows = (
            db.scalars(
                select(RuleViolation).where(RuleViolation.validation_run_id == rules_run.id)
            ).all()
            if rules_run is not None and "rules" in available
            else []
        )
        stat_rows = (
            db.scalars(
                select(StatisticalEvidence).where(
                    StatisticalEvidence.validation_run_id == stats_run.id
                )
            ).all()
            if stats_run is not None and "statistics" in available
            else []
        )
        ml_rows = (
            db.scalars(select(MlEvidence).where(MlEvidence.validation_run_id == ml_run.id)).all()
            if ml_run is not None and "ml" in available
            else []
        )

        grouped: dict[str, dict] = defaultdict(
            lambda: {
                "rules": [],
                "statistics": [],
                "ml": [],
                "enumerator_id": None,
                "cluster_id": None,
                "district_id": None,
            }
        )

        def _touch(record_id: str | None, enumerator, cluster, district) -> dict | None:
            if not record_id:
                return None
            bucket = grouped[str(record_id)]
            bucket["enumerator_id"] = bucket["enumerator_id"] or enumerator
            bucket["cluster_id"] = bucket["cluster_id"] or cluster
            bucket["district_id"] = bucket["district_id"] or district
            return bucket

        for row in rule_rows:
            bucket = _touch(row.record_id, row.enumerator_id, row.cluster_id, row.district_id)
            if bucket is not None:
                bucket["rules"].append(row)
        for row in stat_rows:
            bucket = _touch(row.record_id, row.enumerator_id, row.cluster_id, row.district_id)
            if bucket is not None:
                bucket["statistics"].append(row)
        for row in ml_rows:
            bucket = _touch(row.record_id, row.enumerator_id, row.cluster_id, row.district_id)
            if bucket is not None:
                bucket["ml"].append(row)

        historical = _historical_context(stats_run, ml_rows)
        assessments: list[dict] = []
        debug_rows: list[dict] = []
        empty_bucket = {
            "rules": [],
            "statistics": [],
            "ml": [],
            "enumerator_id": None,
            "cluster_id": None,
            "district_id": None,
        }
        for record_id, bucket in grouped.items():
            fused = _classify_bucket(available, bucket, cfg, historical)
            fused["record_id"] = record_id
            fused["enumerator_id"] = bucket["enumerator_id"]
            fused["cluster_id"] = bucket["cluster_id"]
            fused["district_id"] = bucket["district_id"]
            debug = fused["classification_debug"]
            debug["record_id"] = record_id
            debug_rows.append(debug)
            assessments.append(fused)

        seen = {item["record_id"] for item in assessments}
        for extra in _parquet_records(batch_id):
            if extra["record_id"] in seen:
                continue
            fused = _classify_bucket(available, empty_bucket, cfg, historical)
            fused["record_id"] = extra["record_id"]
            fused["enumerator_id"] = extra["enumerator_id"]
            fused["cluster_id"] = extra["cluster_id"]
            fused["district_id"] = extra["district_id"]
            debug = fused["classification_debug"]
            debug["record_id"] = extra["record_id"]
            debug_rows.append(debug)
            assessments.append(fused)
            seen.add(extra["record_id"])

        detections = list_detections(db, batch_id)
        by_record: dict[str, list] = defaultdict(list)
        by_enum: dict[str, list] = defaultdict(list)
        by_cluster: dict[str, list] = defaultdict(list)
        for item in detections:
            if item.record_id:
                by_record[str(item.record_id)].append(item)
            if item.enumerator_id:
                by_enum[str(item.enumerator_id)].append(item)
            if item.cluster_id:
                by_cluster[str(item.cluster_id)].append(item)
        for fused in assessments:
            related = list(by_record.get(str(fused["record_id"]), []))
            related.extend(by_enum.get(str(fused.get("enumerator_id") or ""), []))
            related.extend(by_cluster.get(str(fused.get("cluster_id") or ""), []))
            types = []
            seen_ids = set()
            compact = []
            for item in related:
                if item.id in seen_ids:
                    continue
                seen_ids.add(item.id)
                types.append(item.detector_type)
                compact.append(
                    {
                        "detector_type": item.detector_type,
                        "entity_type": item.entity_type,
                        "field_name": item.field_name,
                        "observed_value": item.observed_value,
                        "expected_value": item.expected_value,
                        "deviation": item.deviation,
                        "baseline_type": item.baseline_type,
                        "explanation": item.explanation,
                        "classification": item.classification,
                    }
                )
            refs = dict(fused.get("evidence_refs") or {})
            refs["detectors"] = list(dict.fromkeys(types))
            refs["quality_detections"] = compact
            fused["evidence_refs"] = refs
            intel = classify_intelligence(
                anomaly_status=fused.get("anomaly_status") or "NORMAL",
                detector_types=refs["detectors"],
            )
            fused.update(intel)

        dataset_rows = [row for row in stat_rows if not row.record_id]
        dataset_payload = fuse_dataset_context(
            statistical_severities=[row.severity for row in dataset_rows],
            statistical_evidence_ids=[row.id for row in dataset_rows],
            cfg=cfg,
            historical_context=historical,
        )
        persist_assessments(db, run.id, batch_id, assessments)
        persist_dataset_assessment(db, run.id, batch_id, dataset_payload)
        run.status = "COMPLETED"
        run.records_checked = len(assessments)
        run.violation_count = sum(
            1
            for item in assessments
            if item.get("anomaly_status") in {"CONFIRMED", "ANOMALY", "CRITICAL"}
        )
        run.rules_evaluated = len(available)
        run.skipped_rules_json = {
            "engine": "fusion",
            "status": "COMPLETED",
            "available_sources": available,
            "missing_sources": missing,
            "methodology_version": cfg.methodology_version,
            "weights": cfg.weights,
            "has_dataset_assessment": dataset_payload is not None,
            "classification_debug": debug_rows,
        }
        run.completed_at = datetime.now(UTC)
        db.commit()
    except ValidationError:
        run.status = "FAILED"
        run.completed_at = datetime.now(UTC)
        db.commit()
        log_failure("fusion_failed", batch_id=batch_id)
        raise
    except Exception as exc:
        run.status = "FAILED"
        run.completed_at = datetime.now(UTC)
        db.commit()
        log_failure("fusion_failed", batch_id=batch_id)
        raise ValidationError("fusion failed", status_code=500) from exc

    table = ""
    meta = run.skipped_rules_json if isinstance(run.skipped_rules_json, dict) else {}
    debug_rows = list(meta.get("classification_debug") or [])
    if debug_rows:
        table = format_classification_table(debug_rows)
    log_event(
        "fusion_completed",
        batch_id=batch_id,
        records_assessed=run.records_checked,
        confirmed_anomalies=run.violation_count,
        classification_table=table,
    )
    return _summary(run, assessments)


def _summary(run: ValidationRun, items: list[dict]) -> FusionRunResponse:
    meta = run.skipped_rules_json if isinstance(run.skipped_rules_json, dict) else {}

    def count(level: str) -> int:
        return sum(1 for item in items if item.get("severity") == level)

    def classified(status: str) -> int:
        return sum(1 for item in items if item.get("anomaly_status") == status)

    return FusionRunResponse(
        success=run.status in {"COMPLETED", "insufficient"},
        batch_id=run.batch_id,
        validation_run_id=run.id,
        status=str(meta.get("status") or run.status),
        records_assessed=run.records_checked,
        critical=count("CRITICAL"),
        high=count("HIGH"),
        medium=count("MEDIUM"),
        low=count("LOW"),
        confirmed_anomalies=classified("CONFIRMED") + classified("ANOMALY") + classified("CRITICAL"),
        review_signals=classified("REVIEW"),
        available_sources=list(meta.get("available_sources") or []),
        missing_sources=list(meta.get("missing_sources") or []),
        methodology_version=str(meta.get("methodology_version") or ""),
        weights=dict(meta.get("weights") or {}),
        has_dataset_assessment=bool(meta.get("has_dataset_assessment")),
    )
