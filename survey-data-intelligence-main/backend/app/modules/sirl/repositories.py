from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    ClusterProfile,
    DatasetProfile,
    DistrictProfile,
    EnumeratorProfile,
    HistoricalProfile,
    RecordProfile,
    SirlAiEnrichment,
    VariableProfile,
)
from app.modules.sirl.profiler import ProfileBundle
from app.modules.sirl.schemas import AiEnrichment, ProfileCounts, SirlContext, unavailable_enrichment


def delete_profiles(db: Session, batch_id: str) -> None:
    for model in (
        RecordProfile,
        VariableProfile,
        EnumeratorProfile,
        ClusterProfile,
        DistrictProfile,
        DatasetProfile,
        HistoricalProfile,
        SirlAiEnrichment,
    ):
        db.execute(delete(model).where(model.batch_id == batch_id))


def save_bundle(
    db: Session,
    batch_id: str,
    schema_version: str | None,
    bundle: ProfileBundle,
) -> None:
    now = datetime.now(UTC)
    db.add(
        DatasetProfile(
            batch_id=batch_id,
            record_count=int(bundle.dataset["record_count"]),
            column_count=int(bundle.dataset["column_count"]),
            numeric_column_count=int(bundle.dataset["numeric_column_count"]),
            categorical_column_count=int(bundle.dataset["categorical_column_count"]),
            missing_rate=float(bundle.dataset["missing_rate"]),
            duplicate_count=int(bundle.dataset["duplicate_count"]),
            parquet_bytes=bundle.dataset.get("parquet_bytes"),
            profile_json=bundle.dataset,
            profiled_at=bundle.profiled_at,
            created_at=now,
        )
    )
    db.add_all(
        [
            VariableProfile(
                batch_id=batch_id,
                variable_name=item["variable_name"],
                dtype=item["dtype"],
                kind=item["kind"],
                profile_json=item,
                created_at=now,
            )
            for item in bundle.variables
        ]
    )
    db.add_all(
        [
            RecordProfile(
                batch_id=batch_id,
                record_id=item["record_id"],
                enumerator_id=item.get("enumerator_id"),
                cluster_id=item.get("cluster_id"),
                district_id=item.get("district_id"),
                features_json=item,
                created_at=now,
            )
            for item in bundle.records
        ]
    )
    db.add_all(
        [
            EnumeratorProfile(
                batch_id=batch_id,
                enumerator_id=item["id"],
                record_count=item["record_count"],
                profile_json=item,
                created_at=now,
            )
            for item in bundle.enumerators
        ]
    )
    db.add_all(
        [
            ClusterProfile(
                batch_id=batch_id,
                cluster_id=item["id"],
                district_id=None if item.get("related_id") is None else str(item.get("related_id")),
                record_count=item["record_count"],
                profile_json=item,
                created_at=now,
            )
            for item in bundle.clusters
        ]
    )
    db.add_all(
        [
            DistrictProfile(
                batch_id=batch_id,
                district_id=item["id"],
                record_count=item["record_count"],
                profile_json=item,
                created_at=now,
            )
            for item in bundle.districts
        ]
    )
    db.add(
        HistoricalProfile(
            batch_id=batch_id,
            schema_version=schema_version,
            grain="dataset",
            grain_key=batch_id,
            stats_json=bundle.dataset,
            created_at=now,
        )
    )


def load_context(db: Session, batch_id: str) -> SirlContext | None:
    dataset = db.scalars(
        select(DatasetProfile).where(DatasetProfile.batch_id == batch_id)
    ).first()
    if dataset is None:
        return None
    variables = db.scalars(
        select(VariableProfile).where(VariableProfile.batch_id == batch_id)
    ).all()
    records = db.scalars(
        select(RecordProfile).where(RecordProfile.batch_id == batch_id)
    ).all()
    enumerators = db.scalars(
        select(EnumeratorProfile).where(EnumeratorProfile.batch_id == batch_id)
    ).all()
    clusters = db.scalars(
        select(ClusterProfile).where(ClusterProfile.batch_id == batch_id)
    ).all()
    districts = db.scalars(
        select(DistrictProfile).where(DistrictProfile.batch_id == batch_id)
    ).all()
    historical = db.scalars(
        select(HistoricalProfile).where(
            HistoricalProfile.grain == "dataset",
            HistoricalProfile.batch_id != batch_id,
        )
    ).all()
    return SirlContext(
        batch_id=batch_id,
        dataset_context=dataset.profile_json,
        variable_context={row.variable_name: row.profile_json for row in variables},
        record_context=[row.features_json for row in records],
        enumerator_context={row.enumerator_id: row.profile_json for row in enumerators},
        cluster_context={row.cluster_id: row.profile_json for row in clusters},
        district_context={row.district_id: row.profile_json for row in districts},
        historical_context={
            "historical_context_available": bool(historical),
            "priors": [
                {
                    "batch_id": row.batch_id,
                    "grain": row.grain,
                    "grain_key": row.grain_key,
                    "stats": row.stats_json,
                }
                for row in historical
            ],
        },
        ai_enrichment=load_ai_enrichment(db, batch_id),
        profiled_at=dataset.profiled_at,
    )


def profile_counts(db: Session, batch_id: str) -> ProfileCounts:
    dataset = db.scalars(
        select(DatasetProfile).where(DatasetProfile.batch_id == batch_id)
    ).first()
    return ProfileCounts(
        dataset=dataset is not None,
        variables=len(
            db.scalars(select(VariableProfile).where(VariableProfile.batch_id == batch_id)).all()
        ),
        records=len(
            db.scalars(select(RecordProfile).where(RecordProfile.batch_id == batch_id)).all()
        ),
        enumerators=len(
            db.scalars(
                select(EnumeratorProfile).where(EnumeratorProfile.batch_id == batch_id)
            ).all()
        ),
        clusters=len(
            db.scalars(select(ClusterProfile).where(ClusterProfile.batch_id == batch_id)).all()
        ),
        districts=len(
            db.scalars(select(DistrictProfile).where(DistrictProfile.batch_id == batch_id)).all()
        ),
    )


def load_prior_historical(db: Session, batch_id: str, schema_version: str | None) -> dict:
    query = select(HistoricalProfile).where(
        HistoricalProfile.grain == "dataset",
        HistoricalProfile.batch_id != batch_id,
    )
    if schema_version:
        query = query.where(
            (HistoricalProfile.schema_version == schema_version)
            | (HistoricalProfile.schema_version.is_(None))
        )
    rows = db.scalars(query.order_by(HistoricalProfile.created_at.desc()).limit(5)).all()
    if not rows:
        return {"historical_context_available": False, "priors": []}
    return {
        "historical_context_available": True,
        "priors": [
            {
                "batch_id": row.batch_id,
                "grain": row.grain,
                "grain_key": row.grain_key,
                "stats": row.stats_json,
            }
            for row in rows
        ],
    }


def load_ai_enrichment(db: Session, batch_id: str) -> AiEnrichment:
    row = db.scalars(
        select(SirlAiEnrichment).where(SirlAiEnrichment.batch_id == batch_id)
    ).first()
    if row is None:
        return unavailable_enrichment("not_configured")
    payload = row.enrichment_json or {}
    return AiEnrichment(
        enabled=payload.get("enabled", row.status == "available"),
        enriched=payload.get("enriched", row.status == "available"),
        status=row.status if row.status in ("available", "unavailable") else "unavailable",
        reason=row.reason,
        contextual_insights=payload.get("contextual_insights") or [],
        important_relationships=payload.get("important_relationships") or [],
        potential_data_quality_concerns=payload.get("potential_data_quality_concerns") or [],
        context_summary=payload.get("context_summary"),
        confidence=payload.get("confidence"),
    )


def upsert_ai_enrichment(
    db: Session,
    batch_id: str,
    enrichment: AiEnrichment,
    model: str | None,
) -> None:
    row = db.scalars(
        select(SirlAiEnrichment).where(SirlAiEnrichment.batch_id == batch_id)
    ).first()
    payload = enrichment.model_dump()
    if row is None:
        db.add(
            SirlAiEnrichment(
                batch_id=batch_id,
                status=enrichment.status,
                reason=enrichment.reason,
                model=model,
                enrichment_json=payload,
                created_at=datetime.now(UTC),
            )
        )
    else:
        row.status = enrichment.status
        row.reason = enrichment.reason
        row.model = model
        row.enrichment_json = payload
    db.commit()
