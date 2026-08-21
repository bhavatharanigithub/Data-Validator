from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    MlEvidence,
    RuleViolation,
    StatisticalEvidence,
    UnifiedDatasetAssessment,
    UnifiedRiskAssessment,
    ValidationRun,
)
from app.modules.validation.fusion.schemas import UnifiedAssessmentOut
from app.modules.validation.fusion.scoring import (
    EVIDENCE_CONFIDENCE_DESCRIPTION,
    FusionSettings,
    aggregate_scores,
    apply_escalation,
    confidence_score,
    evidence_agreement,
    fuse_dataset_context,
    fuse_record,
    load_fusion_settings,
    normalize_ml_score,
    normalize_rule_severity,
    normalize_stat_severity,
    risk_severity,
    weighted_risk,
)
from tests.conftest import SAMPLES


def _cfg(**overrides) -> FusionSettings:
    base = load_fusion_settings()
    payload = {
        "weights": dict(base.weights),
        "remainder": base.remainder,
        "escalation_min_sources": base.escalation_min_sources,
        "risk_medium": base.risk_medium,
        "risk_high": base.risk_high,
        "risk_critical": base.risk_critical,
        "agreement_spread": base.agreement_spread,
        "methodology_version": base.methodology_version,
    }
    payload.update(overrides)
    return FusionSettings(**payload)


def test_rule_statistical_ml_normalization() -> None:
    assert normalize_rule_severity(None) == 0
    assert normalize_rule_severity("LOW") == 25
    assert normalize_rule_severity("MEDIUM") == 50
    assert normalize_rule_severity("HIGH") == 80
    assert normalize_rule_severity("CRITICAL") == 100
    assert normalize_stat_severity("LOW") == 30
    assert normalize_stat_severity("MEDIUM") == 60
    assert normalize_stat_severity("HIGH") == 90
    assert normalize_stat_severity("CRITICAL") == 100
    assert normalize_ml_score(91) == 91
    assert normalize_ml_score(150) == 100
    assert normalize_ml_score(-5) == 0


def test_aggregation_caps_and_does_not_sum_unbounded() -> None:
    assert aggregate_scores([80], 0.20) == 80
    assert aggregate_scores([80, 80], 0.20) == 96
    assert aggregate_scores([80] * 20, 0.20) == 100
    assert aggregate_scores([50, 30], 0.20) == 50 + 0.20 * 30


def test_missing_source_renormalizes_weights() -> None:
    weights = {"rules": 0.40, "statistics": 0.35, "ml": 0.25}
    risk = weighted_risk({"rules": 80, "statistics": 60}, ["rules", "statistics"], weights)
    expected = 80 * (0.40 / 0.75) + 60 * (0.35 / 0.75)
    assert abs(risk - expected) < 1e-9
    ml_only = weighted_risk({"ml": 91}, ["ml"], weights)
    assert abs(ml_only - 91) < 1e-9
    stats_only = weighted_risk({"statistics": 90}, ["statistics"], weights)
    assert abs(stats_only - 90) < 1e-9
    none = weighted_risk({}, [], weights)
    assert none == 0


def test_unavailable_is_not_treated_as_zero() -> None:
    naive = 80 * 0.40 + 60 * 0.35 + 0 * 0.25
    actual = weighted_risk(
        {"rules": 80, "statistics": 60},
        ["rules", "statistics"],
        {"rules": 0.40, "statistics": 0.35, "ml": 0.25},
    )
    assert actual != naive
    assert actual > naive


def test_all_three_sources_and_zero_evidence() -> None:
    cfg = _cfg()
    fused = fuse_record(
        available=["rules", "statistics", "ml"],
        source_scores={"rules": 0, "statistics": 0, "ml": 0},
        source_severities={"rules": "NONE", "statistics": "NONE", "ml": "NONE"},
        cfg=cfg,
    )
    assert fused["risk_score"] == 0
    assert fused["severity"] == "LOW"
    assert fused["agreement"] == "strong"
    assert 0 <= fused["risk_score"] <= 100


def test_single_source_cases() -> None:
    cfg = _cfg()
    rules_only = fuse_record(
        available=["rules"],
        source_scores={"rules": 80},
        source_severities={"rules": "HIGH"},
        cfg=cfg,
    )
    assert rules_only["agreement"] == "single_source"
    assert rules_only["missing_sources"] == ["statistics", "ml"]
    assert rules_only["risk_score"] == 80
    stats_only = fuse_record(
        available=["statistics"],
        source_scores={"statistics": 90},
        source_severities={"statistics": "HIGH"},
        cfg=cfg,
    )
    assert stats_only["agreement"] == "single_source"
    ml_only = fuse_record(
        available=["ml"],
        source_scores={"ml": 91},
        source_severities={"ml": "HIGH"},
        cfg=cfg,
    )
    assert ml_only["source_scores"]["ml"] == 91
    none = fuse_record(
        available=[],
        source_scores={},
        source_severities={},
        cfg=cfg,
    )
    assert none["agreement"] == "insufficient"
    assert none["confidence"] == 10
    assert none["risk_score"] == 0


def test_two_high_sources_escalate_one_high_does_not() -> None:
    cfg = _cfg()
    two = fuse_record(
        available=["rules", "statistics", "ml"],
        source_scores={"rules": 0, "statistics": 90, "ml": 91},
        source_severities={"rules": "NONE", "statistics": "HIGH", "ml": "HIGH"},
        cfg=cfg,
    )
    assert two["escalation_applied"] is True
    assert two["severity"] in {"HIGH", "CRITICAL"}
    assert two["escalation_reason"]
    one = fuse_record(
        available=["rules", "statistics", "ml"],
        source_scores={"rules": 80, "statistics": 0, "ml": 0},
        source_severities={"rules": "HIGH", "statistics": "NONE", "ml": "NONE"},
        cfg=cfg,
    )
    assert one["escalation_applied"] is False
    score, severity, applied, _ = apply_escalation(
        20, "LOW", {"statistics": "HIGH", "ml": "HIGH"}, ["statistics", "ml"], cfg
    )
    assert applied is True
    assert severity == "HIGH"
    assert score >= cfg.risk_high


def test_agreement_and_confidence() -> None:
    cfg = _cfg()
    strong = evidence_agreement(
        ["rules", "statistics", "ml"],
        {"rules": 0, "statistics": 90, "ml": 91},
        {"rules": "NONE", "statistics": "HIGH", "ml": "HIGH"},
        cfg.agreement_spread,
    )
    mixed = evidence_agreement(
        ["rules", "statistics", "ml"],
        {"rules": 80, "statistics": 30, "ml": 30},
        {"rules": "HIGH", "statistics": "LOW", "ml": "LOW"},
        cfg.agreement_spread,
    )
    assert strong == "strong"
    assert mixed == "mixed"
    one = confidence_score(["rules"], "single_source", False)
    two = confidence_score(["statistics", "ml"], "strong", False)
    three = confidence_score(["rules", "statistics", "ml"], "strong", False)
    conflict = confidence_score(["rules", "statistics", "ml"], "mixed", False)
    assert one < two < three
    assert conflict < three
    assert 0 <= one <= 100
    first = fuse_record(
        available=["rules", "statistics", "ml"],
        source_scores={"rules": 0, "statistics": 90, "ml": 91},
        source_severities={"rules": "NONE", "statistics": "HIGH", "ml": "HIGH"},
        cfg=_cfg(),
    )
    second = fuse_record(
        available=["rules", "statistics", "ml"],
        source_scores={"rules": 0, "statistics": 90, "ml": 91},
        source_severities={"rules": "NONE", "statistics": "HIGH", "ml": "HIGH"},
        cfg=_cfg(),
    )
    assert first["confidence"] == second["confidence"]
    assert first["evidence_confidence"] == first["confidence"]
    assert "not probability" in EVIDENCE_CONFIDENCE_DESCRIPTION.lower()
    assert "probability" in UnifiedAssessmentOut.model_fields["confidence"].description.lower()
    assert "not probability" in UnifiedAssessmentOut.model_fields["confidence"].description.lower()
    schema = UnifiedAssessmentOut.model_json_schema()
    assert "not probability" in schema["properties"]["confidence"]["description"].lower()
    assert schema["properties"]["evidence_confidence"]["description"] == schema["properties"]["confidence"]["description"]


def test_severity_mapping_and_configurable_weights() -> None:
    cfg = _cfg()
    assert risk_severity(0, cfg) == "LOW"
    assert risk_severity(24, cfg) == "LOW"
    assert risk_severity(25, cfg) == "MEDIUM"
    assert risk_severity(50, cfg) == "HIGH"
    assert risk_severity(75, cfg) == "CRITICAL"
    custom = _cfg(weights={"rules": 1.0, "statistics": 0.0, "ml": 0.0})
    fused = fuse_record(
        available=["rules", "statistics"],
        source_scores={"rules": 80, "statistics": 10},
        source_severities={"rules": "HIGH", "statistics": "LOW"},
        cfg=custom,
    )
    assert fused["risk_score"] == 80
    custom_esc = _cfg(escalation_min_sources=3)
    skipped = fuse_record(
        available=["statistics", "ml"],
        source_scores={"statistics": 90, "ml": 91},
        source_severities={"statistics": "HIGH", "ml": "HIGH"},
        cfg=custom_esc,
    )
    assert skipped["escalation_applied"] is False


def test_methodology_version() -> None:
    assert load_fusion_settings().methodology_version == "fusion-v1-prototype"
    fused = fuse_record(
        available=["ml"],
        source_scores={"ml": 10},
        source_severities={"ml": "LOW"},
        cfg=load_fusion_settings(),
    )
    assert fused["methodology_version"] == "fusion-v1-prototype"


def _disable_extra_rules(client: TestClient) -> list[int]:
    extras = [
        item
        for item in client.get("/api/validation/rules").json()
        if item.get("enabled") and not item.get("is_sample")
    ]
    for item in extras:
        client.patch(f"/api/validation/rules/{item['id']}/disable")
    return [item["id"] for item in extras]


def test_fusion_api_idempotency_and_source_immutability(client: TestClient) -> None:
    extras = _disable_extra_rules(client)
    content = (SAMPLES / "survey_ml_demo.csv").read_bytes()
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_ml_demo.csv", content, "text/csv")},
    )
    batch_id = ingest.json()["batch_id"]
    try:
        rules = client.post(f"/api/validation/rules/run/{batch_id}").json()
        stats = client.post(f"/api/validation/statistics/run/{batch_id}").json()
        ml = client.post(f"/api/validation/ml/run/{batch_id}").json()
        assert rules["success"] is True
        assert stats["success"] is True
        assert ml["success"] is True
        first = client.post(f"/api/validation/fusion/run/{batch_id}")
        assert first.status_code == 200
        body = first.json()
        assert body["engine"] == "fusion"
        assert body["success"] is True
        assert body["methodology_version"] == "fusion-v1-prototype"
        assert "rules" in body["weights"]
        detail = client.get(f"/api/validation/fusion/runs/{body['validation_run_id']}")
        assert detail.status_code == 200
        payload = detail.json()
        assert len(payload["items"]) == body["records_assessed"]
        for item in payload["items"]:
            assert 0 <= item["risk_score"] <= 100
            assert 0 <= item["confidence"] <= 100
            assert item["evidence_confidence"] == item["confidence"]
            assert item["methodology_version"] == "fusion-v1-prototype"
            assert "rule_violation_ids" in item["evidence_refs"]
        db = SessionLocal()
        try:
            rule_n = len(db.scalars(select(RuleViolation).where(RuleViolation.batch_id == batch_id)).all())
            stat_n = len(
                db.scalars(select(StatisticalEvidence).where(StatisticalEvidence.batch_id == batch_id)).all()
            )
            ml_n = len(db.scalars(select(MlEvidence).where(MlEvidence.batch_id == batch_id)).all())
        finally:
            db.close()
        second = client.post(f"/api/validation/fusion/run/{batch_id}").json()
        assert second["records_assessed"] == body["records_assessed"]
        db = SessionLocal()
        try:
            fusion_runs = db.scalars(
                select(ValidationRun).where(
                    ValidationRun.batch_id == batch_id,
                    ValidationRun.validation_type == "fusion",
                )
            ).all()
            assert len(fusion_runs) == 1
            assert len(db.scalars(select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)).all()) == second["records_assessed"]
            assert len(db.scalars(select(RuleViolation).where(RuleViolation.batch_id == batch_id)).all()) == rule_n
            assert len(db.scalars(select(StatisticalEvidence).where(StatisticalEvidence.batch_id == batch_id)).all()) == stat_n
            assert len(db.scalars(select(MlEvidence).where(MlEvidence.batch_id == batch_id)).all()) == ml_n
            assert len(db.scalars(select(ValidationRun).where(ValidationRun.batch_id == batch_id, ValidationRun.validation_type == "rules")).all()) == 1
            assert len(db.scalars(select(ValidationRun).where(ValidationRun.batch_id == batch_id, ValidationRun.validation_type == "statistics")).all()) == 1
            assert len(db.scalars(select(ValidationRun).where(ValidationRun.batch_id == batch_id, ValidationRun.validation_type == "ml")).all()) == 1
            assert len(db.scalars(select(UnifiedDatasetAssessment).where(UnifiedDatasetAssessment.batch_id == batch_id)).all()) <= 1
        finally:
            db.close()
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_fusion_insufficient_when_no_engines_ran(client: TestClient) -> None:
    content = (SAMPLES / "survey_sample.csv").read_bytes()
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_sample.csv", content, "text/csv")},
        params={"auto_pipeline": "false"},
    )
    batch_id = ingest.json()["batch_id"]
    result = client.post(f"/api/validation/fusion/run/{batch_id}")
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "insufficient"
    assert body["records_assessed"] == 0
    assert body["available_sources"] == []


def test_fusion_excludes_unavailable_ml(client: TestClient) -> None:
    extras = _disable_extra_rules(client)
    content = (SAMPLES / "survey_invalid.csv").read_bytes()
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_invalid.csv", content, "text/csv")},
        params={"auto_pipeline": "false"},
    )
    batch_id = ingest.json()["batch_id"]
    try:
        client.post(f"/api/validation/rules/run/{batch_id}")
        client.post(f"/api/validation/statistics/run/{batch_id}")
        fused = client.post(f"/api/validation/fusion/run/{batch_id}").json()
        assert "ml" not in fused["available_sources"]
        assert "ml" in fused["missing_sources"]
        detail = client.get(f"/api/validation/fusion/runs/{fused['validation_run_id']}").json()
        for item in detail["items"]:
            assert "ml" not in item["source_scores"]
            assert 0 <= item["risk_score"] <= 100
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_fusion_nonexistent_batch(client: TestClient) -> None:
    assert client.post("/api/validation/fusion/run/BATCH_NOPE").status_code == 404


def test_dataset_context_is_not_assigned_to_records() -> None:
    payload = fuse_dataset_context(
        statistical_severities=["HIGH"],
        statistical_evidence_ids=[999],
        cfg=_cfg(),
    )
    assert payload is not None
    assert payload["scope"] == "dataset"
    assert payload["not_a_record_risk"] is True
    assert "record_id" not in payload
    assert payload["statistical_evidence_ids"] == [999]
    assert payload["evidence_confidence"] == payload["confidence"]
    assert fuse_dataset_context(statistical_severities=[], statistical_evidence_ids=[], cfg=_cfg()) is None


def test_dataset_level_statistical_evidence_is_preserved(client: TestClient) -> None:
    extras = _disable_extra_rules(client)
    content = (SAMPLES / "survey_invalid.csv").read_bytes()
    ingest = client.post(
        "/api/ingest/csv",
        files={"file": ("survey_invalid.csv", content, "text/csv")},
    )
    batch_id = ingest.json()["batch_id"]
    try:
        client.post(f"/api/validation/rules/run/{batch_id}")
        stats = client.post(f"/api/validation/statistics/run/{batch_id}").json()
        db = SessionLocal()
        try:
            stats_run = db.scalars(
                select(ValidationRun).where(
                    ValidationRun.batch_id == batch_id,
                    ValidationRun.validation_type == "statistics",
                )
            ).first()
            assert stats_run is not None
            dataset_row = StatisticalEvidence(
                validation_run_id=stats_run.id,
                batch_id=batch_id,
                record_id=None,
                variable="synth_unemployment_pct",
                detector="historical_shift",
                scope="dataset",
                severity="HIGH",
                evidence_json={"scope": "dataset", "synthetic": True},
                created_at=datetime.now(UTC),
            )
            db.add(dataset_row)
            db.commit()
            db.refresh(dataset_row)
            dataset_id = dataset_row.id
        finally:
            db.close()
        fused = client.post(f"/api/validation/fusion/run/{batch_id}").json()
        detail = client.get(f"/api/validation/fusion/runs/{fused['validation_run_id']}").json()
        dataset = detail["dataset_assessment"]
        assert fused["has_dataset_assessment"] is True
        assert dataset is not None
        assert dataset["scope"] == "dataset"
        assert dataset["not_a_record_risk"] is True
        assert dataset_id in dataset["statistical_evidence_ids"]
        assert "risk_score" not in dataset
        for item in detail["items"]:
            assert dataset_id not in item["evidence_refs"]["statistical_evidence_ids"]
            assert item["record_id"] is not None
        db = SessionLocal()
        try:
            stored_stats = db.scalars(
                select(StatisticalEvidence).where(StatisticalEvidence.id == dataset_id)
            ).first()
            assert stored_stats is not None
            assert stored_stats.record_id is None
            assert stored_stats.scope == "dataset"
        finally:
            db.close()
        client.post(f"/api/validation/fusion/run/{batch_id}")
        db = SessionLocal()
        try:
            dataset_rows = db.scalars(
                select(UnifiedDatasetAssessment).where(UnifiedDatasetAssessment.batch_id == batch_id)
            ).all()
            assert len(dataset_rows) == 1
        finally:
            db.close()
        del stats
    finally:
        for rule_id in extras:
            client.patch(f"/api/validation/rules/{rule_id}/enable")
