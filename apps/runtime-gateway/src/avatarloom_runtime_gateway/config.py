"""Runtime Gateway 配置。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime Gateway 配置。"""

    model_config = SettingsConfigDict(
        env_prefix="AVATARLOOM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8101

    # Control API 地址（用于查询 profile/persona）
    control_api_url: str = "http://127.0.0.1:8100"

    # 存储
    workspace_root: str = "."
    artifacts_root: str = "./data/artifacts"
    runs_root: str = "./data/runs"

    # 默认 Profile（未指定时）
    default_profile: str = "mock"

    # 日志
    log_level: str = "INFO"


def load_settings() -> Settings:
    return Settings()
