from app.modules.sirl.profiler import ProfileBundle
from app.modules.sirl.schemas import SirlContext


def bundle_to_context(batch_id: str, bundle: ProfileBundle) -> SirlContext:
    return SirlContext(
        batch_id=batch_id,
        dataset_context=bundle.dataset,
        variable_context={item["variable_name"]: item for item in bundle.variables},
        record_context=bundle.records,
        enumerator_context={item["id"]: item for item in bundle.enumerators},
        cluster_context={item["id"]: item for item in bundle.clusters},
        district_context={item["id"]: item for item in bundle.districts},
        historical_context=bundle.historical,
        profiled_at=bundle.profiled_at,
    )
