"""轻量 Bearer token 鉴权依赖。

行为：
- token 未配置（空）→ 鉴权关闭（开发模式），直接放行。
- 已配置 → 请求必须带 ``Authorization: Bearer <token>``，且与配置一致；否则 401。

token 来源（统一入口，优先级从高到低）：
1. ``app.state.settings.api_token`` —— ``create_app`` 注入的 Settings 实例
   （测试可直接 ``Settings(api_token=...)`` 注入；pydantic-settings 本身已从
   环境变量 ``AVATARLOOM_API_TOKEN`` / .env 读取，二者天然一致）。
2. 环境变量 ``AVATARLOOM_API_TOKEN`` —— 兜底（lifespan 未跑、app.state 无
   settings 时仍能工作，保留旧的纯 env 行为）。

挂载方式（在 ``app.py`` 创建 FastAPI 时）：

    app = FastAPI(..., dependencies=[Depends(verify_token)])

所有 router（含未来新增的）会自动受保护。
"""

from __future__ import annotations

import os
import secrets
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

if TYPE_CHECKING:
    from avatarloom_control_api.config import Settings

# 全局 bearer security scheme —— 不 auto_error，以便在 token 未配置时也能通过依赖。
_bearer_scheme = HTTPBearer(auto_error=False)

# env 名（Settings 用 env_prefix="AVATARLOOM_"，字段 api_token 对应此 env）。
_EXPECTED_TOKEN_ENV = "AVATARLOOM_API_TOKEN"


def _expected_token(request: Request) -> str:
    """读取生效的 token。

    优先取 app.state.settings.api_token（Settings 为权威来源——含 env/.env/显式注入）；
    app.state 没有 settings 时回退环境变量，保持旧的纯 env 行为。
    返回空串 → 鉴权关闭（开发模式）。
    """
    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is not None:
        return (settings.api_token or "").strip()
    return os.environ.get(_EXPECTED_TOKEN_ENV, "").strip()


async def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> bool:
    """全局鉴权依赖。

    - 配置未设 token → 视为开发模式，直接放行。
    - 配置设了 token 但请求未带 / scheme 错 / token 不匹配 → 401。
    - token 匹配 → 返回 True。
    """
    expected = _expected_token(request)
    if not expected:
        # 鉴权关闭：token 未配置。
        return True

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header. Expected: Bearer <token>.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # constant-time 比较防侧信道。
    if not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True
