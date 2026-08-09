"""Runtime Gateway WebSocket 入口校验（Origin + token）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from avatarloom_runtime_gateway.config import Settings

logger = logging.getLogger(__name__)

# HTTP 端点 Bearer 依赖（不 auto_error，便于 fail-closed 分支自行抛 401）
_http_bearer = HTTPBearer(auto_error=False)


def origin_allowed(origin: str | None, settings: Settings) -> bool:
    """Origin 是否在白名单。缺 Origin（非浏览器客户端）视为允许。"""
    if not origin:
        return True
    allowed = settings.cors_origins
    return "*" in allowed or origin in allowed


def presented_header_token(ws: WebSocket) -> str:
    """取服务端客户端在握手中出示的 Bearer token。"""
    auth = ws.headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    if scheme.lower() == "bearer" and value:
        return value.strip()
    return ""


def token_matches(presented: str, expected: str) -> bool:
    """常量时间比较 token。"""
    return bool(presented) and secrets.compare_digest(presented, expected)


def issue_ws_ticket(secret: str, *, ttl_seconds: int = 60, now: int | None = None) -> str:
    """签发浏览器可见的短期 WS ticket，避免把长期控制面 token 打进 bundle。"""
    if not secret:
        raise ValueError("secret must not be empty")
    issued_at = int(time.time() if now is None else now)
    payload: dict[str, Any] = {
        "aud": "avatarloom-ws",
        "exp": issued_at + max(1, min(ttl_seconds, 300)),
        "nonce": secrets.token_urlsafe(12),
    }
    payload_bytes = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
    return f"{payload_b64}.{_b64url_encode(signature.digest())}"


def verify_ws_ticket(ticket: str, secret: str, *, now: int | None = None) -> bool:
    """校验短期 WS ticket 的签名、受众和过期时间。任何解析异常均 fail-closed。"""
    if not ticket or not secret:
        return False
    payload_b64, separator, signature_b64 = ticket.partition(".")
    if not separator or not payload_b64 or not signature_b64:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
    try:
        presented = _b64url_decode(signature_b64)
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not hmac.compare_digest(presented, expected.digest()) or not isinstance(payload, dict):
        return False
    current = int(time.time() if now is None else now)
    exp = payload.get("exp")
    return (
        payload.get("aud") == "avatarloom-ws"
        and isinstance(exp, int)
        and current < exp <= current + 300
        and isinstance(payload.get("nonce"), str)
    )


def browser_token_authenticated(presented: str, expected: str) -> bool:
    """浏览器首条 auth 消息支持短期 ticket；保留长期 token 仅供旧客户端兼容。"""
    return token_matches(presented, expected) or verify_ws_ticket(presented, expected)


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def header_token_authenticated(ws: WebSocket, settings: Settings) -> bool:
    """握手 Authorization 是否已经完成鉴权。

    token 未配置时仅显式开发模式（auth_disabled=True）视为已鉴权。
    """
    expected = settings.api_token.strip()
    if not expected:
        return settings.auth_disabled
    return token_matches(presented_header_token(ws), expected)


def verify_http_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
) -> bool:
    """HTTP 端点鉴权依赖（fail-closed，与 control-api 同语义）。

    - api_token 为空且 auth_disabled=True → 开发模式放行
    - api_token 为空且 auth_disabled=False → 401（生产漏配不裸奔）
    - api_token 非空 → 校验 Authorization: Bearer <token>
    """
    settings: Settings | None = getattr(request.app.state, "settings", None)
    expected = (settings.api_token if settings is not None else "").strip()
    if not expected:
        if settings is not None and settings.auth_disabled:
            return True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is not configured. Set AVATARLOOM_API_TOKEN or AVATARLOOM_AUTH_DISABLED=1.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header. Expected: Bearer <token>.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not token_matches(credentials.credentials, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True


async def verify_ws_access(ws: WebSocket, settings: Settings) -> bool:
    """校验握手 Origin 和可选的服务端 Bearer token。

    浏览器无法设置 Authorization，因此 token 配置时由 ``WebSocketSession``
    在握手后读取一次 auth 消息完成浏览器鉴权。token 未配置且未显式关闭鉴权
    （auth_disabled=False）时 fail-closed：accept 前拒绝（HTTP 403）。
    """
    origin = ws.headers.get("origin")
    if not origin_allowed(origin, settings):
        logger.warning("ws rejected: origin %r not in whitelist", origin)
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return False

    expected = settings.api_token.strip()
    if not expected and not settings.auth_disabled:
        logger.warning("ws rejected: no api_token configured and auth not disabled (origin=%r)", origin)
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return False
    if expected:
        header_token = presented_header_token(ws)
        if header_token and not token_matches(header_token, expected):
            logger.warning("ws rejected: invalid Authorization token (origin=%r)", origin)
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return False

    return True
