from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False, "timeout": 30}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    from app import models as _models  # noqa: F401
    from app.modules.auth.seed import seed_users
    from app.modules.validation.seed import seed_sample_validation
    from app.modules.validation.intelligence.registry import seed_detectors

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "processed").mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if "batches" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("batches")}
        if "survey_code" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE batches ADD COLUMN survey_code VARCHAR(64) DEFAULT 'DEMO'"
                    )
                )
    if "unified_risk_assessments" in inspector.get_table_names():
        fusion_columns = {
            column["name"] for column in inspector.get_columns("unified_risk_assessments")
        }
        with engine.begin() as connection:
            if "anomaly_status" not in fusion_columns:
                connection.execute(
                    text(
                        "ALTER TABLE unified_risk_assessments ADD COLUMN anomaly_status VARCHAR(16) DEFAULT 'NORMAL'"
                    )
                )
            if "classification_reason" not in fusion_columns:
                connection.execute(
                    text(
                        "ALTER TABLE unified_risk_assessments ADD COLUMN classification_reason VARCHAR(64)"
                    )
                )
            if "intelligence_classification" not in fusion_columns:
                connection.execute(
                    text(
                        "ALTER TABLE unified_risk_assessments ADD COLUMN intelligence_classification VARCHAR(32)"
                    )
                )
            if "primary_detector" not in fusion_columns:
                connection.execute(
                    text(
                        "ALTER TABLE unified_risk_assessments ADD COLUMN primary_detector VARCHAR(64)"
                    )
                )
            if "detector_count" not in fusion_columns:
                connection.execute(
                    text("ALTER TABLE unified_risk_assessments ADD COLUMN detector_count INTEGER")
                )
            if "review_required" not in fusion_columns:
                connection.execute(
                    text(
                        "ALTER TABLE unified_risk_assessments ADD COLUMN review_required BOOLEAN DEFAULT 0"
                    )
                )
    if "batches" in inspector.get_table_names():
        batch_columns = {column["name"] for column in inspector.get_columns("batches")}
        if "input_hash" not in batch_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE batches ADD COLUMN input_hash VARCHAR(64)")
                )
    if "pipeline_runs" in inspector.get_table_names():
        run_columns = {column["name"] for column in inspector.get_columns("pipeline_runs")}
        with engine.begin() as connection:
            if "error_code" not in run_columns:
                connection.execute(
                    text("ALTER TABLE pipeline_runs ADD COLUMN error_code VARCHAR(64)")
                )
            if "is_active" not in run_columns:
                connection.execute(
                    text(
                        "ALTER TABLE pipeline_runs ADD COLUMN is_active BOOLEAN DEFAULT 0"
                    )
                )
    if "investigations" in inspector.get_table_names():
        inv_columns = {column["name"] for column in inspector.get_columns("investigations")}
        with engine.begin() as connection:
            if "finding" not in inv_columns:
                connection.execute(text("ALTER TABLE investigations ADD COLUMN finding TEXT"))
            if "action_taken" not in inv_columns:
                connection.execute(
                    text("ALTER TABLE investigations ADD COLUMN action_taken VARCHAR(64)")
                )
            if "final_classification" not in inv_columns:
                connection.execute(
                    text(
                        "ALTER TABLE investigations ADD COLUMN final_classification VARCHAR(32)"
                    )
                )
    db = SessionLocal()
    try:
        seed_sample_validation(db)
        seed_detectors(db)
        seed_users(db)
    finally:
        db.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
