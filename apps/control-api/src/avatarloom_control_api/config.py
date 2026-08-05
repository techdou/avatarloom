"""Control API 配置。"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Control API 配置。优先级：环境变量 > .env > 默认。"""

    model_config = SettingsConfigDict(
        env_prefix="AVATARLOOM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 服务
    host: str = "127.0.0.1"
    port: int = 8100

    # 数据库
    db_url: str = Field(
        default="sqlite+aiosqlite:///./data/avatarloom.db",
        description="SQLAlchemy async URL",
    )

    # 存储
    workspace_root: str = "."
    artifacts_root: str = "./data/artifacts"
    runs_root: str = "./data/runs"

    # 鉴权：留空（默认）→ 鉴权关闭（开发模式）；填值 → 所有端点要求 Bearer token
    api_token: str = Field(
        default="",
        description="Bearer token required by all endpoints when set; empty disables auth.",
    )

    # CORS 白名单（与 allow_credentials=True 配合使用，禁用通配符）
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins (Studio frontend defaults included).",
    )

    # 日志
    log_level: str = "INFO"


def load_settings() -> Settings:
    """从环境加载 Settings。"""
    return Settings()


def ensure_dirs(settings: Settings) -> None:
    """确保关键目录存在。"""
    Path(settings.workspace_root).mkdir(parents=True, exist_ok=True)
    Path(settings.artifacts_root).mkdir(parents=True, exist_ok=True)
    Path(settings.runs_root).mkdir(parents=True, exist_ok=True)
    # db 文件目录
    if "sqlite" in settings.db_url:
        db_path = settings.db_url.split("///")[-1]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
