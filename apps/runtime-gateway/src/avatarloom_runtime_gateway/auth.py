"""Runtime Gateway WebSocket 入口校验（Origin + token）。"""

from __future__ import annotations

import logging
import secrets

from fastapi import WebSocket, status

from avatarloom_runtime_gateway.config import Settings

logger = logging.getLogger(__name__)


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


def header_token_authenticated(ws: WebSocket, settings: Settings) -> bool:
    """握手 Authorization 是否已经完成鉴权。

    token 未配置时仅显式开发模式（auth_disabled=True）视为已鉴权。
    """
    expected = settings.api_token.strip()
    if not expected:
        return settings.auth_disabled
    return token_matches(presented_header_token(ws), expected)


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
