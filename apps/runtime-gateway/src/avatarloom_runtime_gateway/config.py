"""Runtime Gateway 配置。"""

from __future__ import annotations

from pydantic import AliasChoices, Field
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
    # 端口走独立别名：避免与 control-api 共用 AVATARLOOM_PORT 撞车。
    # .env 里写 AVATARLOOM_RUNTIME_GATEWAY_PORT=8101（或兼容旧名 AVATARLOOM_PORT）。
    port: int = Field(
        default=8101,
        validation_alias=AliasChoices("AVATARLOOM_RUNTIME_GATEWAY_PORT", "AVATARLOOM_PORT"),
    )

    # Control API 地址（用于查询 profile/persona）
    control_api_url: str = "http://127.0.0.1:8100"

    # Control API 鉴权：与 control-api 的 AVATARLOOM_API_TOKEN 一致。
    # control-api 关闭鉴权时留空即可（不会发送 Authorization header）。
    control_api_token: str = Field(
        default="",
        description="Bearer token for Control API; empty sends no Authorization header.",
    )

    # CORS 白名单（allow_credentials=True 时不能用通配符）
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins (Studio frontend defaults included).",
    )

    # 存储
    workspace_root: str = "."
    artifacts_root: str = "./data/artifacts"
    runs_root: str = "./data/runs"

    # 默认 Profile（未指定时）
    default_profile: str = "autodl-best"

    # 日志
    log_level: str = "INFO"


def load_settings() -> Settings:
    return Settings()


def control_api_auth_headers(settings: Settings) -> dict[str, str]:
    """构造调 control-api 时的 Authorization header。

    - control_api_token 为空 → 返回空 dict（不发送 header，对应开发模式）。
    - 非空 → 返回 ``{"Authorization": "Bearer <token>"}``。
    """
    token = settings.control_api_token.strip()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}

