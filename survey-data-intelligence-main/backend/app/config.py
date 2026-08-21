from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py → backend/ → repository root
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


def _settings_env_files() -> tuple[str, ...]:
    """Absolute env files so CWD (repo root vs backend/) does not matter.

    Repository-root `.env` is loaded first; `backend/.env` overrides it.
    Process environment variables still take precedence over both files.
    """
    return (
        str((PROJECT_ROOT / ".env").resolve()),
        str((BACKEND_DIR / ".env").resolve()),
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_settings_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default=f"sqlite:///{(PROJECT_ROOT / 'data' / 'app.db').resolve()}"
    )
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    esigma_base_url: str = ""
    esigma_api_key: str = ""
    esigma_timeout_seconds: float = 30
    esigma_mock_mode: bool = True
    ai_provider: str = ""
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_timeout_seconds: int = 30
    ai_max_retries: int = 2
    ai_retry_backoff_ms: int = 100
    supervisor_user: str = "hsd"
    supervisor_pass: str = ""
    jwt_secret: str = "change-me-hackathon-jwt-secret-32"
    auth_demo_mode: bool = True
    auth_cookie_name: str = "sv_access"
    auth_cookie_secure: bool = False
    auth_token_minutes: int = 480
    auth_admin_user: str = "admin"
    auth_admin_password: str = "admin"
    auth_supervisor_user: str = "supervisor"
    auth_supervisor_password: str = "supervisor"
    ai_max_context_bytes: int = 16384
    stats_z_medium_threshold: float = 2.0
    stats_z_high_threshold: float = 3.0
    stats_iqr_multiplier: float = 1.5
    stats_iqr_outer_multiplier: float = 3.0
    stats_min_observations: int = 8
    stats_min_group_observations: int = 5
    stats_std_epsilon: float = 1e-9
    stats_historical_relative_medium: float = 0.5
    stats_historical_relative_high: float = 1.0
    ml_n_estimators: int = 100
    ml_contamination: str = "auto"
    ml_random_state: int = 42
    ml_min_training_records: int = 32
    ml_min_features: int = 2
    ml_score_medium_threshold: float = 60.0
    ml_score_high_threshold: float = 80.0
    fusion_weight_rules: float = 0.40
    fusion_weight_statistics: float = 0.35
    fusion_weight_ml: float = 0.25
    fusion_aggregation_remainder: float = 0.20
    fusion_escalation_min_sources: int = 2
    fusion_risk_medium_threshold: float = 25.0
    fusion_risk_high_threshold: float = 50.0
    fusion_risk_critical_threshold: float = 75.0
    fusion_agreement_spread: float = 40.0
    fusion_methodology_version: str = "fusion-v1-prototype"
    ai_explanation_max_context_bytes: int = 16384
    ai_explanation_batch_limit: int = 20
    ai_explanation_all_limit: int = 200
    ai_explanation_concurrency: int = 3
    max_concurrent_pipelines: int = 1
    max_stage_retries: int = 2
    pipeline_sync_jobs: bool = False
    pipeline_queue_stall_seconds: int = 60
    ingest_reuse_completed: bool = True
    ocr_max_upload_mb: int = 20

    @model_validator(mode="after")
    def resolve_project_paths(self) -> "Settings":
        if not self.data_dir.is_absolute():
            self.data_dir = (PROJECT_ROOT / self.data_dir).resolve()

        sqlite_prefix = "sqlite:///"
        if self.database_url.startswith(sqlite_prefix):
            raw_path = self.database_url[len(sqlite_prefix) :]
            db_path = Path(raw_path)
            if not db_path.is_absolute():
                db_path = (PROJECT_ROOT / db_path).resolve()
            self.database_url = f"sqlite:///{db_path}"
        return self


settings = Settings()
