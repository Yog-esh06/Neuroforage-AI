"""Central configuration. All infrastructure assumptions come from environment variables."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    database_url: str = f"sqlite:///{(REPO_ROOT / 'storage' / 'neuroforge.db').as_posix()}"

    job_backend: str = "inline"  # inline | celery
    redis_url: str = "redis://localhost:6379/0"

    storage_backend: str = "local"  # local | s3
    storage_dir: str = str(REPO_ROOT / "storage" / "documents")
    artifacts_dir: str = str(REPO_ROOT / "storage" / "artifacts")
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    max_upload_mb: int = 50
    max_pages: int = 500
    allowed_extensions: str = "pdf,png,jpg,jpeg,tif,tiff,bmp,webp,txt,md,csv,xlsx,xls,docx"

    auth_enabled: bool = True
    jwt_secret: str = "change-me-in-production-use-openssl-rand-hex-32"
    jwt_expire_minutes: int = 480
    seed_admin_email: str = "admin@neuroforge.local"
    seed_admin_password: str = "neuroforge-admin"
    seed_admin_name: str = "Platform Admin"

    llm_provider: str = "extractive"
    llm_model: str = ""
    llm_api_key: str = Field(default="", repr=False)
    llm_base_url: str = ""
    llm_timeout_seconds: int = 60

    embedding_backend: str = "hashing"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 1024

    ocr_engine: str = "auto"
    ocr_min_chars_per_page: int = 40
    spacy_model: str = "en_core_web_sm"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_ext_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_extensions.split(",") if e.strip()}

    def validate_for_production(self) -> list[str]:
        problems = []
        if self.is_production:
            if self.jwt_secret.startswith("change-me"):
                problems.append("JWT_SECRET must be set in production")
            if self.seed_admin_password == "neuroforge-admin":
                problems.append("SEED_ADMIN_PASSWORD must be changed in production")
            if not self.auth_enabled:
                problems.append("AUTH_ENABLED must be true in production")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
