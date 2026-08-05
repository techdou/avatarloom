"""轻量 Bearer token 鉴权依赖。

行为：
- 若 ``AVATARLOOM_API_TOKEN`` 未设置（空）→ 鉴权关闭（开发模式），直接放行。
- 若已设置 → 请求必须带 ``Authorization: Bearer <token>``，且 token 与配置一致；否则 401。

挂载方式（在 ``app.py`` 创建 FastAPI 时）：

    app = FastAPI(..., dependencies=[Depends(verify_token)])

所有 router（含未来新增的）会自动受保护。
"""

from __future__ import annotations

import os
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# 全局 bearer security scheme —— 不 auto_error，以便在 token 未配置时也能通过依赖。
_bearer_scheme = HTTPBearer(auto_error=False)

# 单次读取 env；运行期不变（与 pydantic Settings 一致）。
# 注意：Settings 用 env_prefix="AVATARLOOM_"，所以 env 名是 AVATARLOOM_API_TOKEN。
_EXPECTED_TOKEN_ENV = "AVATARLOOM_API_TOKEN"


def _expected_token() -> str:
    """读取配置的 token。env 未设 → 空串 → 鉴权关闭。"""
    return os.environ.get(_EXPECTED_TOKEN_ENV, "").strip()


async def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> bool:
    """全局鉴权依赖。

    - 配置未设 token → 视为开发模式，直接放行。
    - 配置设了 token 但请求未带 / scheme 错 / token 不匹配 → 401。
    - token 匹配 → 返回 True。
    """
    expected = _expected_token()
    if not expected:
        # 鉴权关闭：env 没设 token。
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
