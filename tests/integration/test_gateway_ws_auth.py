"""Runtime Gateway WS 入口安全测试：token、Origin、persona_id 校验与错误脱敏。

沿用 test_gateway_ws.py 的真实 uvicorn + websockets 客户端模式。
websockets 17 顶层 connect 是新 asyncio 客户端：
- 握手被拒抛 InvalidStatus（.response.status_code）
- 自定义 Origin 用 origin= 参数，自定义头用 additional_headers=
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn
import websockets
from avatarloom_runtime_gateway.app import create_app
from avatarloom_runtime_gateway.auth import issue_ws_ticket
from avatarloom_runtime_gateway.config import Settings


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def _gateway(tmp_path: Path, **overrides) -> Iterator[tuple[str, int]]:
    """按 overrides 构造 Settings 起真实 Gateway，yield (host, port)。"""
    port = _free_port()
    base = {
        "host": "127.0.0.1",
        "port": port,
        "workspace_root": str(tmp_path),
        "artifacts_root": str(tmp_path / "artifacts"),
        "runs_root": str(tmp_path / "runs"),
        "default_profile": "mock",
        # 非鉴权测试默认走显式开发模式；鉴权契约由 TestWsTokenAuth 单独覆盖。
        "auth_disabled": True,
    }
    base.update(overrides)
    app = create_app(Settings(**base))
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline and not server.started:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("server failed to start")
    try:
        yield "127.0.0.1", port
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _url(host: str, port: int, query: str = "") -> str:
    return f"ws://{host}:{port}/ws/realtime{query}"


async def _recv_until(ws, msg_type: str, timeout: float = 5) -> dict | None:
    """循环收 JSON 消息直到指定 type 或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(deadline - time.time(), 0.1))
        except TimeoutError:
            return None
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
                if data.get("type") == msg_type:
                    return data
            except json.JSONDecodeError:
                continue
    return None


async def _assert_rejected_403(connect_coro) -> None:
    """握手应被拒（accept 前 close → uvicorn 转 HTTP 403）。"""
    with pytest.raises(websockets.exceptions.InvalidStatus) as ei:
        await connect_coro
    assert ei.value.response.status_code == 403


# ---------------------------------------------------------------------------
# token 校验
# ---------------------------------------------------------------------------


class TestWsTokenAuth:
    async def test_empty_token_dev_mode_allows(self, tmp_path: Path) -> None:
        """空 token + 显式 auth_disabled=True = 开发模式：无凭证也能连。"""
        with _gateway(tmp_path, auth_disabled=True) as (host, port):
            async with websockets.connect(_url(host, port)) as ws:
                await ws.send(json.dumps({"type": "ping"}))
                assert await _recv_until(ws, "pong") is not None

    async def test_empty_token_fail_closed_by_default(self, tmp_path: Path) -> None:
        """空 token 且未显式关闭鉴权（默认）→ 握手被拒（HTTP 403，fail-closed）。"""
        with _gateway(tmp_path, auth_disabled=False) as (host, port):
            await _assert_rejected_403(websockets.connect(_url(host, port)))

    async def test_missing_token_rejected_after_handshake(self, tmp_path: Path) -> None:
        """浏览器连接先握手，未发送 auth 消息时由应用以 1008 关闭。"""
        with _gateway(tmp_path, api_token="s3cret") as (host, port):
            async with websockets.connect(_url(host, port)) as ws:
                with pytest.raises(websockets.exceptions.ConnectionClosed) as ei:
                    await ws.recv()
                assert ei.value.rcvd.code == 1008

    async def test_wrong_token_rejected_after_handshake(self, tmp_path: Path) -> None:
        with _gateway(tmp_path, api_token="s3cret") as (host, port):
            async with websockets.connect(_url(host, port)) as ws:
                await ws.send(json.dumps({"type": "auth", "token": "wrong"}))
                with pytest.raises(websockets.exceptions.ConnectionClosed) as ei:
                    await ws.recv()
                assert ei.value.rcvd.code == 1008

    async def test_auth_message_accepted(self, tmp_path: Path) -> None:
        """浏览器通过首条 auth JSON 消息完成鉴权。"""
        with _gateway(tmp_path, api_token="s3cret") as (host, port):
            async with websockets.connect(_url(host, port)) as ws:
                await ws.send(json.dumps({"type": "auth", "token": "s3cret"}))
                await ws.send(json.dumps({"type": "ping"}))
                assert await _recv_until(ws, "pong") is not None

    async def test_short_lived_ticket_accepted(self, tmp_path: Path) -> None:
        """Studio 使用服务端签发的短期 ticket，不需要获得长期 API token。"""
        with _gateway(tmp_path, api_token="s3cret") as (host, port):
            ticket = issue_ws_ticket("s3cret")
            async with websockets.connect(_url(host, port)) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ticket}))
                await ws.send(json.dumps({"type": "ping"}))
                assert await _recv_until(ws, "pong") is not None

    async def test_expired_ticket_rejected(self, tmp_path: Path) -> None:
        with _gateway(tmp_path, api_token="s3cret") as (host, port):
            ticket = issue_ws_ticket("s3cret", ttl_seconds=1, now=1)
            async with websockets.connect(_url(host, port)) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ticket}))
                with pytest.raises(websockets.exceptions.ConnectionClosed) as ei:
                    await ws.recv()
                assert ei.value.rcvd.code == 1008

    async def test_bearer_header_accepted(self, tmp_path: Path) -> None:
        """脚本/服务端客户端可走 Authorization: Bearer。"""
        with _gateway(tmp_path, api_token="s3cret") as (host, port):
            async with websockets.connect(
                _url(host, port),
                additional_headers={"Authorization": "Bearer s3cret"},
            ) as ws:
                await ws.send(json.dumps({"type": "ping"}))
                assert await _recv_until(ws, "pong") is not None


# ---------------------------------------------------------------------------
# Origin 校验
# ---------------------------------------------------------------------------


class TestWsOriginCheck:
    async def test_origin_not_in_whitelist_rejected(self, tmp_path: Path) -> None:
        """开发模式（无 token）下 Origin 白名单仍生效。"""
        with _gateway(tmp_path) as (host, port):
            await _assert_rejected_403(
                websockets.connect(_url(host, port), origin="http://evil.example")
            )

    async def test_origin_in_whitelist_accepted(self, tmp_path: Path) -> None:
        with _gateway(tmp_path) as (host, port):
            async with websockets.connect(
                _url(host, port), origin="http://localhost:3000"
            ) as ws:
                await ws.send(json.dumps({"type": "ping"}))
                assert await _recv_until(ws, "pong") is not None

    async def test_no_origin_allowed(self, tmp_path: Path) -> None:
        """非浏览器客户端不带 Origin → 放行（test_empty_token_dev_mode_allows 已覆盖，
        这里显式锁定语义）。"""
        with _gateway(tmp_path) as (host, port):
            async with websockets.connect(_url(host, port)) as ws:
                await ws.send(json.dumps({"type": "ping"}))
                assert await _recv_until(ws, "pong") is not None


# ---------------------------------------------------------------------------
# persona_id 校验 + 错误脱敏
# ---------------------------------------------------------------------------


class TestPersonaIdBoundary:
    async def _start_mock_session(self, ws, **payload_extra) -> dict | None:
        await ws.send(
            json.dumps({"type": "session.start", "payload": {"profile_id": "mock", **payload_extra}})
        )
        return await _recv_until(ws, "session.started", timeout=8)

    async def test_session_start_invalid_persona_id(self, tmp_path: Path) -> None:
        with _gateway(tmp_path) as (host, port):
            async with websockets.connect(_url(host, port)) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "type": "session.start",
                            "payload": {"profile_id": "mock", "persona_id": "../evil"},
                        }
                    )
                )
                err = await _recv_until(ws, "error", timeout=5)
                assert err is not None
                assert "persona_id" in err["payload"]["message"]
                # 连接应仍可用（校验失败不杀连接）
                await ws.send(json.dumps({"type": "ping"}))
                assert await _recv_until(ws, "pong") is not None

    async def test_persona_set_invalid_id(self, tmp_path: Path) -> None:
        with _gateway(tmp_path) as (host, port):
            async with websockets.connect(_url(host, port)) as ws:
                assert await self._start_mock_session(ws) is not None
                await ws.send(
                    json.dumps({"type": "persona.set", "payload": {"persona_id": "../../x"}})
                )
                err = await _recv_until(ws, "error", timeout=5)
                assert err is not None
                assert "invalid persona_id" in err["payload"]["message"]

    async def test_persona_set_error_sanitized(self, tmp_path: Path) -> None:
        """加载失败对外只回通用信息——不泄漏服务器路径/异常原文。"""
        with _gateway(tmp_path) as (host, port):
            async with websockets.connect(_url(host, port)) as ws:
                assert await self._start_mock_session(ws) is not None
                await ws.send(
                    json.dumps({"type": "persona.set", "payload": {"persona_id": "ghost"}})
                )
                err = await _recv_until(ws, "error", timeout=5)
                assert err is not None
                msg = err["payload"]["message"]
                assert "切换失败" in msg
                # 脱敏断言：不含内部细节
                assert "persona.yaml" not in msg
                assert "not found" not in msg.lower()
                assert str(tmp_path) not in msg
