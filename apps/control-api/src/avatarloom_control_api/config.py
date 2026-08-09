"""Control API 配置。"""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 把 .env 加载进 os.environ——pydantic-settings 的 env_file 只填 Settings 字段，
# 不写入 os.environ。secrets router 用 os.environ.get() 查 key 是否设置，
# 不加载的话本地 dev 场景恒显示"未设置"（key 明明在 .env 里、runtime 实际可用）。
try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:
    pass  # python-dotenv 未装时降级——pydantic-settings 自带 env_file 仍可用


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
    # 端口走独立别名：避免与 gateway 共用 AVATARLOOM_PORT 撞车。
    # .env 里写 AVATARLOOM_CONTROL_API_PORT=8100（或兼容旧名 AVATARLOOM_PORT）。
    port: int = Field(
        default=8100,
        validation_alias=AliasChoices("AVATARLOOM_CONTROL_API_PORT", "AVATARLOOM_PORT"),
    )

    # 数据库
    db_url: str = Field(
        default="sqlite+aiosqlite:///./data/avatarloom.db",
        description="SQLAlchemy async URL",
    )

    # 存储
    workspace_root: str = "."
    artifacts_root: str = "./data/artifacts"
    runs_root: str = "./data/runs"

    # 鉴权：token 非空时要求 Bearer；token 为空时必须显式 auth_disabled=True 才放行。
    api_token: str = Field(
        default="",
        description="Bearer token required by all endpoints when set; empty remains fail-closed unless auth_disabled.",
    )
    # 显式开发模式开关：api_token 为空且 auth_disabled=False（默认）时 fail-closed（401），
    # 防止生产漏配 token 直接裸奔；本地开发需显式设置 AVATARLOOM_AUTH_DISABLED=1。
    auth_disabled: bool = Field(
        default=False,
        description="Explicit dev-mode switch: allow unauthenticated access when api_token is empty.",
    )

    # CORS 白名单（与 allow_credentials=True 配合使用，禁用通配符）
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:13000",
            "http://127.0.0.1:13000",
        ],
        description="Allowed CORS origins (Studio and tunnel defaults included).",
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
