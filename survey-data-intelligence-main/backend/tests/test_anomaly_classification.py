import json

from app.modules.validation.fusion.classification import (
    CONFIRMED,
    NORMAL,
    REVIEW,
    classify_anomaly_status,
    format_classification_table,
    is_confirmed_anomaly,
    should_auto_explain,
)
from app.modules.validation.fusion.scoring import fuse_record, load_fusion_settings


def test_hard_rule_age_negative_is_critical_anomaly() -> None:
    result = classify_anomaly_status(
        source_scores={"rules": 80, "statistics": 90, "ml": 70},
        source_severities={"rules": "HIGH", "statistics": "HIGH", "ml": "HIGH"},
        evidence_refs={
            "rule_violation_ids": [1],
            "rule_codes": ["AGE_MIN"],
            "statistical_evidence_ids": [2],
            "ml_evidence_ids": [3],
        },
    )
    assert result["anomaly_status"] == CONFIRMED
    assert result["classification_reason"] == "hard_rule_violation"


def test_hard_rule_hours_and_income_are_confirmed() -> None:
    hours = classify_anomaly_status(
        source_scores={"rules": 100},
        source_severities={"rules": "CRITICAL"},
        evidence_refs={"rule_violation_ids": [10], "rule_codes": ["WORKING_HOURS_MAX"]},
    )
    income = classify_anomaly_status(
        source_scores={"rules": 80},
        source_severities={"rules": "HIGH"},
        evidence_refs={"rule_violation_ids": [11], "rule_codes": ["INCOME_NON_NEGATIVE"]},
    )
    assert hours["anomaly_status"] == CONFIRMED
    assert income["anomaly_status"] == CONFIRMED


def test_valid_age_85_is_not_automatically_anomaly() -> None:
    result = classify_anomaly_status(
        source_scores={"rules": 0, "statistics": 90, "ml": 0},
        source_severities={"rules": "NONE", "statistics": "HIGH", "ml": "NONE"},
        evidence_refs={"statistical_evidence_ids": [1]},
    )
    assert result["anomaly_status"] == REVIEW
    assert not is_confirmed_anomaly(type("A", (), {"evidence_refs_json": {"statistical_evidence_ids": [1]}, "source_scores_json": {"statistics": 90}, "source_severities_json": {"statistics": "HIGH"}})())


def test_high_valid_income_and_hours_are_review_or_normal() -> None:
    income = classify_anomaly_status(
        source_scores={"statistics": 60},
        source_severities={"statistics": "MEDIUM"},
        evidence_refs={"statistical_evidence_ids": [1]},
    )
    hours = classify_anomaly_status(
        source_scores={"statistics": 30},
        source_severities={"statistics": "LOW"},
        evidence_refs={"statistical_evidence_ids": [2]},
    )
    assert income["anomaly_status"] == REVIEW
    assert hours["anomaly_status"] == REVIEW


def test_ml_only_is_not_confirmed_anomaly() -> None:
    result = classify_anomaly_status(
        source_scores={"ml": 91},
        source_severities={"ml": "HIGH"},
        evidence_refs={"ml_evidence_ids": [3]},
    )
    assert result["anomaly_status"] == REVIEW
    assert result["classification_reason"] == "ml_only_unusual"


def test_statistics_only_is_not_confirmed_anomaly() -> None:
    result = classify_anomaly_status(
        source_scores={"statistics": 90},
        source_severities={"statistics": "HIGH"},
        evidence_refs={"statistical_evidence_ids": [4]},
    )
    assert result["anomaly_status"] == REVIEW
    assert result["classification_reason"] == "statistics_only_unusual"


def test_strong_stats_and_ml_are_review_not_anomaly() -> None:
    result = classify_anomaly_status(
        source_scores={"statistics": 90, "ml": 85},
        source_severities={"statistics": "HIGH", "ml": "HIGH"},
        evidence_refs={"statistical_evidence_ids": [1], "ml_evidence_ids": [2]},
    )
    assert result["anomaly_status"] == REVIEW
    assert result["classification_reason"] == "unusual_without_validity_violation"


def test_weak_stats_and_ml_stay_review() -> None:
    result = classify_anomaly_status(
        source_scores={"statistics": 30, "ml": 20},
        source_severities={"statistics": "LOW", "ml": "LOW"},
        evidence_refs={"statistical_evidence_ids": [1], "ml_evidence_ids": [2]},
    )
    assert result["anomaly_status"] == REVIEW


def test_multi_variable_statistics_are_not_confirmed() -> None:
    result = classify_anomaly_status(
        source_scores={"statistics": 90},
        source_severities={"statistics": "HIGH"},
        evidence_refs={"statistical_evidence_ids": [1, 2]},
        high_stat_variables=["age", "income"],
    )
    assert result["anomaly_status"] == REVIEW


def test_risk_score_or_severity_alone_is_not_anomaly() -> None:
    fused = fuse_record(
        available=["statistics", "ml"],
        source_scores={"statistics": 90, "ml": 80},
        source_severities={"statistics": "HIGH", "ml": "HIGH"},
        cfg=load_fusion_settings(),
    )
    assert fused["risk_score"] >= 80
    assert fused["severity"] in {"HIGH", "CRITICAL"}
    classified = classify_anomaly_status(
        source_scores=fused["source_scores"],
        source_severities=fused["source_severities"],
        evidence_refs={"statistical_evidence_ids": [1], "ml_evidence_ids": [2]},
    )
    assert classified["anomaly_status"] == REVIEW


def test_rule_plus_ml_or_stats_remains_confirmed() -> None:
    both = classify_anomaly_status(
        source_scores={"rules": 80, "ml": 70},
        source_severities={"rules": "HIGH", "ml": "HIGH"},
        evidence_refs={"rule_violation_ids": [1], "rule_codes": ["AGE_MIN"], "ml_evidence_ids": [2]},
    )
    stats = classify_anomaly_status(
        source_scores={"rules": 80, "statistics": 90},
        source_severities={"rules": "HIGH", "statistics": "HIGH"},
        evidence_refs={
            "rule_violation_ids": [1],
            "rule_codes": ["INCOME_NON_NEGATIVE"],
            "statistical_evidence_ids": [2],
        },
    )
    assert both["anomaly_status"] == CONFIRMED
    assert stats["anomaly_status"] == CONFIRMED


def test_clean_record_is_normal_and_not_explained() -> None:
    result = classify_anomaly_status(
        source_scores={"rules": 0, "statistics": 0, "ml": 0},
        source_severities={"rules": "NONE", "statistics": "NONE", "ml": "NONE"},
        evidence_refs={},
    )
    assert result["anomaly_status"] == NORMAL
    dummy = type(
        "A",
        (),
        {
            "evidence_refs_json": {},
            "source_scores_json": {},
            "source_severities_json": {},
        },
    )()
    assert should_auto_explain(dummy) is False


def test_phase6_risk_score_unchanged_by_classification() -> None:
    cfg = load_fusion_settings()
    fused = fuse_record(
        available=["ml"],
        source_scores={"ml": 91},
        source_severities={"ml": "HIGH"},
        cfg=cfg,
    )
    classified = classify_anomaly_status(
        source_scores=fused["source_scores"],
        source_severities=fused["source_severities"],
        evidence_refs={"ml_evidence_ids": [1]},
    )
    assert fused["risk_score"] == 91
    assert fused["severity"] == "CRITICAL"
    assert classified["anomaly_status"] == REVIEW
    assert "anomaly_status" not in fused


def test_quality_csv_dashboard_returns_confirmed_rule_anomalies(client, monkeypatch) -> None:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import MlEvidence, RuleViolation, StatisticalEvidence, UnifiedRiskAssessment
    from tests.conftest import SAMPLES
    from tests.test_validation_explanation import FakeProvider, VALID_EXPLANATION

    extras = [
        item
        for item in client.get("/api/validation/rules").json()
        if item.get("enabled") and not item.get("is_sample")
    ]
    for item in extras:
        client.patch(f"/api/validation/rules/{item['id']}/disable")
    fake = FakeProvider(payload=VALID_EXPLANATION)
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        ingest = client.post(
            "/api/ingest/csv",
            files={
                "file": (
                    "survey_quality_40.csv",
                    (SAMPLES / "survey_quality_40.csv").read_bytes(),
                    "text/csv",
                )
            },
        )
        batch_id = ingest.json()["batch_id"]
        client.post(f"/api/pipeline/run/{batch_id}")
        db = SessionLocal()
        try:
            fused = list(
                db.scalars(
                    select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)
                ).all()
            )
            rules = {
                row.record_id
                for row in db.scalars(select(RuleViolation).where(RuleViolation.batch_id == batch_id)).all()
            }
            stats = {
                row.record_id
                for row in db.scalars(
                    select(StatisticalEvidence).where(StatisticalEvidence.batch_id == batch_id)
                ).all()
                if row.record_id
            }
            ml = {
                row.record_id
                for row in db.scalars(select(MlEvidence).where(MlEvidence.batch_id == batch_id)).all()
            }
        finally:
            db.close()
        expected = {"M030", "M033", "M036"}
        assert expected <= rules
        confirmed = {row.record_id for row in fused if is_confirmed_anomaly(row)}
        assert confirmed == expected
        for record_id in ("M016", "M012", "M026", "M031", "M032", "M034", "M037", "M039"):
            assert record_id not in confirmed
        debug_rows = []
        for row in fused:
            classified = classify_anomaly_status(
                source_scores=row.source_scores_json,
                source_severities=row.source_severities_json,
                evidence_refs=row.evidence_refs_json,
            )
            refs = row.evidence_refs_json or {}
            debug_rows.append(
                {
                    "record_id": row.record_id,
                    "risk_score": row.risk_score,
                    "severity": row.severity,
                    "rule_signal": bool(refs.get("rule_violation_ids")),
                    "statistics_signal": bool(refs.get("statistical_evidence_ids")),
                    "ml_signal": bool(refs.get("ml_evidence_ids")),
                    "anomaly_status": classified["anomaly_status"],
                    "anomaly_reason": classified["classification_reason"],
                }
            )
        print("\n" + format_classification_table(debug_rows))
        queue = client.get(
            "/api/dashboard/anomalies",
            params={"batch_id": batch_id, "page": 1, "page_size": 50},
        ).json()
        queue_ids = {item["record_id"] for item in queue["items"]}
        assert queue_ids == expected
        for item in queue["items"]:
            assert item["anomaly_status"] == CONFIRMED
        ml_only = ml - stats - rules
        stats_only = stats - ml - rules
        for record_id in ml_only | stats_only:
            assert record_id not in queue_ids
        explained = {json.loads(payload)["unified_assessment"]["record_id"] for payload in fake.users}
        for record_id in expected:
            assert record_id in explained
        m001 = next(row for row in fused if row.record_id == "M001")
        if should_auto_explain(m001):
            assert "M001" in explained
        else:
            assert "M001" not in explained
        assert len(fused) == 40
        by_status = {}
        for row in fused:
            by_status.setdefault(classify_anomaly_status(
                source_scores=row.source_scores_json,
                source_severities=row.source_severities_json,
                evidence_refs=row.evidence_refs_json,
            )["anomaly_status"], set()).add(row.record_id)
        assert by_status.get(CONFIRMED) == expected
        assert {"M031", "M032", "M034"} <= by_status.get(REVIEW, set())
        assert len(by_status.get(CONFIRMED, set())) == 3
        assert sum(len(ids) for ids in by_status.values()) == 40
    finally:
        for item in extras:
            client.patch(f"/api/validation/rules/{item['id']}/enable")


def test_high_risk_without_validity_rule_is_normal() -> None:
    for risk, severity in ((82, "CRITICAL"), (74, "HIGH"), (50, "MEDIUM")):
        result = classify_anomaly_status(
            source_scores={"rules": 0, "statistics": 0, "ml": 0},
            source_severities={"rules": "NONE", "statistics": "NONE", "ml": "NONE"},
            evidence_refs={},
        )
        dummy = type(
            "A",
            (),
            {
                "risk_score": risk,
                "severity": severity,
                "evidence_refs_json": {},
                "source_scores_json": {"rules": 0, "statistics": 0, "ml": 0},
                "source_severities_json": {"rules": severity, "statistics": "NONE", "ml": "NONE"},
            },
        )()
        assert result["anomaly_status"] == NORMAL
        assert not is_confirmed_anomaly(dummy)


def test_lookup_rule_is_not_confirmed() -> None:
    result = classify_anomaly_status(
        source_scores={"rules": 55},
        source_severities={"rules": "MEDIUM"},
        evidence_refs={"rule_violation_ids": [9], "rule_codes": ["CLUSTER_IN_REFERENCE", "ENUMERATOR_IN_REFERENCE"]},
    )
    assert result["anomaly_status"] == NORMAL
    assert not is_confirmed_anomaly(
        type(
            "A",
            (),
            {
                "evidence_refs_json": {"rule_codes": ["DISTRICT_IN_REFERENCE"]},
                "source_scores_json": {"rules": 40},
                "source_severities_json": {"rules": "MEDIUM"},
            },
        )()
    )


def test_requested_record_matrix_risk_cannot_promote() -> None:
    m016 = classify_anomaly_status(
        source_scores={"rules": 0, "statistics": 0, "ml": 0},
        source_severities={"rules": "CRITICAL", "statistics": "NONE", "ml": "NONE"},
        evidence_refs={},
    )
    m039 = classify_anomaly_status(
        source_scores={"rules": 0},
        source_severities={"rules": "HIGH"},
        evidence_refs={},
    )
    m019 = classify_anomaly_status(
        source_scores={"rules": 0},
        source_severities={"rules": "MEDIUM"},
        evidence_refs={},
    )
    m031 = classify_anomaly_status(
        source_scores={"statistics": 70},
        source_severities={"statistics": "HIGH"},
        evidence_refs={"statistical_evidence_ids": [1]},
    )
    m032 = classify_anomaly_status(
        source_scores={"statistics": 65},
        source_severities={"statistics": "HIGH"},
        evidence_refs={"statistical_evidence_ids": [2]},
    )
    m034 = classify_anomaly_status(
        source_scores={"statistics": 80},
        source_severities={"statistics": "HIGH"},
        evidence_refs={"statistical_evidence_ids": [3]},
    )
    m030 = classify_anomaly_status(
        source_scores={"rules": 100},
        source_severities={"rules": "CRITICAL"},
        evidence_refs={"rule_violation_ids": [1], "rule_codes": ["AGE_MIN"]},
    )
    m033 = classify_anomaly_status(
        source_scores={"rules": 100},
        source_severities={"rules": "CRITICAL"},
        evidence_refs={"rule_violation_ids": [2], "rule_codes": ["WORKING_HOURS_MAX"]},
    )
    m036 = classify_anomaly_status(
        source_scores={"rules": 100},
        source_severities={"rules": "CRITICAL"},
        evidence_refs={"rule_violation_ids": [3], "rule_codes": ["INCOME_NON_NEGATIVE"]},
    )
    assert m016["anomaly_status"] == NORMAL
    assert m039["anomaly_status"] == NORMAL
    assert m019["anomaly_status"] == NORMAL
    assert m031["anomaly_status"] == REVIEW
    assert m032["anomaly_status"] == REVIEW
    assert m034["anomaly_status"] == REVIEW
    assert m030["anomaly_status"] == CONFIRMED
    assert m033["anomaly_status"] == CONFIRMED
    assert m036["anomaly_status"] == CONFIRMED
    promoted = classify_anomaly_status(
        source_scores={"rules": 0, "statistics": 0, "ml": 0},
        source_severities={"overall": "CRITICAL"},
        evidence_refs={},
    )
    assert promoted["anomaly_status"] != CONFIRMED
    assert promoted["anomaly_status"] == NORMAL


def test_anomalies_api_ignores_phase6_severity_for_queue(client, monkeypatch) -> None:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import UnifiedRiskAssessment
    from tests.conftest import SAMPLES
    from tests.test_validation_explanation import FakeProvider, VALID_EXPLANATION

    extras = [
        item
        for item in client.get("/api/validation/rules").json()
        if item.get("enabled") and not item.get("is_sample")
    ]
    for item in extras:
        client.patch(f"/api/validation/rules/{item['id']}/disable")
    fake = FakeProvider(payload=VALID_EXPLANATION)
    monkeypatch.setattr(
        "app.modules.validation.explanation.service.build_ai_provider",
        lambda *args, **kwargs: fake,
    )
    try:
        ingest = client.post(
            "/api/ingest/csv",
            files={
                "file": (
                    "survey_quality_40.csv",
                    (SAMPLES / "survey_quality_40.csv").read_bytes(),
                    "text/csv",
                )
            },
        )
        batch_id = ingest.json()["batch_id"]
        client.post(f"/api/pipeline/run/{batch_id}")
        db = SessionLocal()
        try:
            fused = list(
                db.scalars(
                    select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)
                ).all()
            )
        finally:
            db.close()
        by_id = {row.record_id: row for row in fused}
        for record_id in ("M016", "M019", "M020", "M039"):
            row = by_id[record_id]
            assert not is_confirmed_anomaly(row)
        queue = client.get(
            "/api/dashboard/anomalies",
            params={"batch_id": batch_id, "page": 1, "page_size": 50},
        ).json()
        queue_ids = {item["record_id"] for item in queue["items"]}
        assert queue_ids == {"M030", "M033", "M036"}
        for record_id in ("M016", "M019", "M020", "M039"):
            assert record_id not in queue_ids
        high_only = client.get(
            "/api/dashboard/anomalies",
            params={"batch_id": batch_id, "page": 1, "page_size": 50, "severity": "HIGH"},
        ).json()
        for item in high_only["items"]:
            assert item["record_id"] in {"M030", "M033", "M036"}
            assert item["anomaly_status"] == CONFIRMED
    finally:
        for item in extras:
            client.patch(f"/api/validation/rules/{item['id']}/enable")

