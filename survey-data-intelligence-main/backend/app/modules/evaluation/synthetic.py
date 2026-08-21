from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.config import PROJECT_ROOT, settings
from app.modules.validation.explanation.selector import has_detected_evidence
from app.modules.validation.fusion.classification import is_confirmed_anomaly, should_auto_explain

SAMPLES = PROJECT_ROOT / "data" / "samples"
GROUND_TRUTH_PATH = SAMPLES / "survey_anomaly_ground_truth.json"
DEMO_CSV = SAMPLES / "survey_demo_40.csv"

REVIEW_LABELS = {"clear_anomaly", "borderline_unusual", "multi_source_extreme"}


def load_ground_truth() -> dict[str, dict]:
    payload = json.loads(GROUND_TRUTH_PATH.read_text())
    return {item["record_id"]: item for item in payload["records"]}


def _disable_extras(client: TestClient) -> list[int]:
    extras = [
        item
        for item in client.get("/api/validation/rules").json()
        if item.get("enabled") and not item.get("is_sample")
    ]
    for item in extras:
        client.patch(f"/api/validation/rules/{item['id']}/disable")
    return [item["id"] for item in extras]


def _enable(client: TestClient, rule_ids: list[int]) -> None:
    for rule_id in rule_ids:
        client.patch(f"/api/validation/rules/{rule_id}/enable")


def _rates(true_pos: int, false_pos: int, false_neg: int) -> tuple[float, float]:
    precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) else 0.0
    recall = true_pos / (true_pos + false_neg) if (true_pos + false_neg) else 0.0
    return precision, recall


def _confusion(predicted: set[str], actual: set[str]) -> dict:
    tp = len(predicted & actual)
    fp = len(predicted - actual)
    fn = len(actual - predicted)
    precision, recall = _rates(tp, fp, fn)
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
    }


def evaluate_demo_dataset(client: TestClient, fake_provider=None) -> dict:
    """Run the controlled 40-row CSV through the real pipeline. Labels stay out of engines."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import MlEvidence, RuleViolation, StatisticalEvidence, UnifiedRiskAssessment

    truth = load_ground_truth()
    extras = _disable_extras(client)
    try:
        ingest = client.post(
            "/api/ingest/csv",
            files={"file": ("survey_demo_40.csv", DEMO_CSV.read_bytes(), "text/csv")},
        )
        batch_id = ingest.json()["batch_id"]
        pipeline = client.post(f"/api/pipeline/run/{batch_id}").json()
        detail = client.get(f"/api/pipeline/{pipeline['pipeline_run_id']}").json()
        db = SessionLocal()
        try:
            rules = {
                row.record_id
                for row in db.scalars(select(RuleViolation).where(RuleViolation.batch_id == batch_id)).all()
            }
            stats = {
                row.record_id
                for row in db.scalars(
                    select(StatisticalEvidence).where(StatisticalEvidence.batch_id == batch_id)
                ).all()
            }
            ml = {
                row.record_id
                for row in db.scalars(select(MlEvidence).where(MlEvidence.batch_id == batch_id)).all()
            }
            fused = list(
                db.scalars(select(UnifiedRiskAssessment).where(UnifiedRiskAssessment.batch_id == batch_id)).all()
            )
        finally:
            db.close()
        fused_ids = {row.record_id for row in fused}
        detected = {row.record_id for row in fused if has_detected_evidence(row)}
        confirmed = {row.record_id for row in fused if is_confirmed_anomaly(row)}
        review_ids = {row.record_id for row in fused if not is_confirmed_anomaly(row) and should_auto_explain(row)}
        all_ids = {f"M{i:03d}" for i in range(1, 41)}
        clean = all_ids - set(truth)
        review = {rid for rid, item in truth.items() if item["ground_truth"] in REVIEW_LABELS}
        rule_truth = {rid for rid, item in truth.items() if item.get("expect_rule")}
        explained: list[str] = []
        for user in getattr(fake_provider, "users", []) or []:
            context = json.loads(user)
            explained.append(str(context.get("unified_assessment", {}).get("record_id") or ""))
        explanation_stage = next(item for item in detail["stages"] if item["stage"] == "EXPLANATION")
        return {
            "batch_id": batch_id,
            "pipeline_status": detail["status"],
            "intentionally_anomalous": len(review),
            "intentionally_clean": len(clean),
            "flagged_by_rules": len(rules),
            "flagged_by_statistics": len(stats),
            "flagged_by_ml": len(ml),
            "fused_assessments": len(fused_ids),
            "detected_evidence": len(detected),
            "confirmed_anomalies": len(confirmed),
            "review_signals": len(review_ids),
            "rule_metrics": _confusion(rules, rule_truth),
            "fusion_metrics": _confusion(confirmed, rule_truth),
            "confirmed_ids": sorted(confirmed),
            "review_ids": sorted(review_ids),
            "clean_sent_to_ai": sorted(rid for rid in explained if rid in clean),
            "ai_calls": len(explained),
            "explained_ids": explained,
            "explanation_status": explanation_stage["status"],
            "ai_records_processed": explanation_stage.get("records_processed"),
            "concurrency_cap": min(max(int(settings.ai_explanation_concurrency), 1), 8),
            "rules_ids": sorted(rules),
            "stats_ids": sorted(stats),
            "ml_ids": sorted(ml),
            "detected_ids": sorted(detected),
        }
    finally:
        _enable(client, extras)
