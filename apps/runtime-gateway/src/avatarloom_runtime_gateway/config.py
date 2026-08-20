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
    # .env 里写 AVATARLOOM_RUNTIME_GATEWAY_PORT=27811（或兼容旧名 AVATARLOOM_PORT）。
    port: int = Field(
        default=27811,
        validation_alias=AliasChoices("AVATARLOOM_RUNTIME_GATEWAY_PORT", "AVATARLOOM_PORT"),
    )

    # Control API 地址（用于查询 profile/persona）
    control_api_url: str = "http://127.0.0.1:27810"

    # Control API 鉴权：与 control-api 的 AVATARLOOM_API_TOKEN 一致。
    # control-api 关闭鉴权时留空即可（不会发送 Authorization header）。
    control_api_token: str = Field(
        default="",
        description="Bearer token for Control API; empty sends no Authorization header.",
    )

    # WS 入口鉴权：与 control-api 共用 env 名 AVATARLOOM_API_TOKEN（env_prefix 一致），
    # 一套 token 同时保护 control-api HTTP 与 gateway WS。
    # 留空（默认）→ /ws/realtime 不校验 token（开发模式）；
    # 填值 → 浏览器首条 auth 消息带 token；脚本客户端用 Authorization: Bearer <token>。
    api_token: str = Field(
        default="",
        description="Bearer token required on /ws/realtime when set; empty disables auth (dev mode).",
    )
    # 显式开发模式开关：api_token 为空且 auth_disabled=False（默认）时 fail-closed
    # （WS 握手直接拒绝），防止生产漏配 token 时任何人可发起 GPU 会话。
    auth_disabled: bool = Field(
        default=False,
        description="Explicit dev-mode switch: allow unauthenticated WS when api_token is empty.",
    )

    # CORS 白名单（allow_credentials=True 时不能用通配符）
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:27300",
            "http://127.0.0.1:27300",
        ],
        description="Allowed CORS origins (Studio and tunnel defaults included).",
    )

    # 存储
    workspace_root: str = "."
    artifacts_root: str = "./data/artifacts"
    runs_root: str = "./data/runs"

    # 默认 Profile（未指定时）——local-5070 是本机真实后端（VAD/LLM/TTS 真 adapter，
    # STT 受 funasr/Py3.12 限制走 mock）；mock 仅作无 GPU 时的降级，需显式设
    # AVATARLOOM_DEFAULT_PROFILE=mock 才走假链路。AutoDL 生产经 env 指定 autodl-best。
    default_profile: str = "local-5070"

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

