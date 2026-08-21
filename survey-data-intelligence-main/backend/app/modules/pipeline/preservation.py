from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PipelineRun, PipelineStageRun

_PROTECTED_RUN_IDS: ContextVar[frozenset[int]] = ContextVar(
    "pipeline_protected_validation_run_ids",
    default=frozenset(),
)


def protected_validation_run_ids(db: Session, batch_id: str) -> set[int]:
    """Engine run ids belonging to the currently ACTIVE pipeline run for a batch."""
    active = db.scalars(
        select(PipelineRun).where(
            PipelineRun.batch_id == batch_id,
            PipelineRun.is_active.is_(True),
        )
    ).all()
    ids: set[int] = set()
    for run in active:
        stages = db.scalars(
            select(PipelineStageRun).where(PipelineStageRun.pipeline_run_id == run.id)
        ).all()
        for stage in stages:
            if stage.engine_run_id:
                ids.add(int(stage.engine_run_id))
    return ids


def protected_ids_for_replace() -> set[int]:
    return set(_PROTECTED_RUN_IDS.get())


@contextmanager
def preserve_active_engine_runs(db: Session, batch_id: str):
    token = _PROTECTED_RUN_IDS.set(frozenset(protected_validation_run_ids(db, batch_id)))
    try:
        yield
    finally:
        _PROTECTED_RUN_IDS.reset(token)
