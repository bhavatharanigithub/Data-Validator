from app.modules.validation.fusion.classification import classify_anomaly_status, classify_intelligence
from app.modules.validation.fusion.scoring import fuse_record, load_fusion_settings


def test_fusion_score_unchanged_by_intelligence_label() -> None:
    cfg = load_fusion_settings()
    fused = fuse_record(
        available=["statistics"],
        source_scores={"statistics": 70},
        source_severities={"statistics": "HIGH"},
        cfg=cfg,
    )
    classified = classify_anomaly_status(
        source_scores=fused["source_scores"],
        evidence_refs={"statistical_evidence_ids": [1]},
    )
    intel = classify_intelligence(anomaly_status=classified["anomaly_status"], detector_types=["ENUMERATOR_DEVIATION"])
    assert fused["risk_score"] == 70
    assert intel["intelligence_classification"] in {"UNUSUAL_PATTERN", "INVESTIGATION_REQUIRED"}
    assert classified["anomaly_status"] == "REVIEW"
