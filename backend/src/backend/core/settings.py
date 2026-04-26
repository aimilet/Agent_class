from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ZHUJIAO_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "助教 Agent"
    api_host: str = "127.0.0.1"
    api_port: int = 18080
    log_level: str = "INFO"
    runtime_root: str | None = None
    database_url: str | None = None
    allowed_path_roots: list[str] = Field(default_factory=list)
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 2
    llm_api_mode: str = "responses"
    llm_json_method: str = "json_schema"
    mock_llm_enabled: bool = False
    mock_llm_model_name: str = "mock-structured-llm"
    default_review_scale: int = 100
    max_answer_rounds: int = 3
    max_agent_retries: int = 2
    review_parallelism: int = 4
    submission_unpack_max_depth: int = 4
    submission_unpack_max_files: int = 120
    vision_max_assets_per_submission: int = 6

    @property
    def backend_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    @property
    def package_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def resolved_runtime_root(self) -> Path:
        if self.runtime_root:
            return Path(self.runtime_root).expanduser().resolve()
        return self.backend_root / "runtime"

    @property
    def uploads_root(self) -> Path:
        return self.resolved_runtime_root / "uploads"

    @property
    def artifacts_root(self) -> Path:
        return self.resolved_runtime_root / "artifacts"

    @property
    def logs_root(self) -> Path:
        return self.resolved_runtime_root / "logs"

    @property
    def quarantine_root(self) -> Path:
        return self.resolved_runtime_root / "quarantine"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        database_path = self.resolved_runtime_root / "zhujiao.sqlite3"
        return f"sqlite:///{database_path.as_posix()}"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def normalized_allowed_path_roots(self) -> list[Path]:
        configured = [Path(item).expanduser().resolve() for item in self.allowed_path_roots]
        defaults = [self.backend_root.resolve(), self.resolved_runtime_root.resolve()]
        merged: list[Path] = []
        for path in [*configured, *defaults]:
            if path not in merged:
                merged.append(path)
        return merged

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.resolved_runtime_root,
            self.uploads_root,
            self.artifacts_root,
            self.logs_root,
            self.quarantine_root,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_runtime_dirs()
    return settings
