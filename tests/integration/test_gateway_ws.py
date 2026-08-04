"""Runtime Gateway WebSocket 集成测试。

Starlette 1.x 的 TestClient 不再支持 httpx WS——改用真实启动 uvicorn 服务 +
websockets 客户端做端到端验证。更接近真实浏览器场景。
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import Iterator

import numpy as np
import pytest
import uvicorn
import websockets
from avatarloom_runtime_gateway.app import create_app
from avatarloom_runtime_gateway.config import Settings


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def gateway_server(tmp_path) -> Iterator[tuple[str, int]]:
    """启动真实 Gateway 服务，返回 (host, port)。"""
    port = _free_port()
    settings = Settings(
        host="127.0.0.1",
        port=port,
        workspace_root=str(tmp_path),
        artifacts_root=str(tmp_path / "artifacts"),
        runs_root=str(tmp_path / "runs"),
        default_profile="mock",
    )
    app = create_app(settings)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # 等服务起来
    deadline = time.time() + 10
    while time.time() < deadline:
        if server.started:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("server failed to start")

    yield ("127.0.0.1", port)

    server.should_exit = True
    thread.join(timeout=5)


async def _ws_connect(host: str, port: int) -> websockets.WebSocketClientProtocol:
    """连接 ws 并返回 client。"""
    return await websockets.connect(f"ws://{host}:{port}/ws/realtime")


class TestGatewayHTTP:
    def test_root(self, gateway_server) -> None:
        import httpx

        host, port = gateway_server
        r = httpx.get(f"http://{host}:{port}/", timeout=5)
        assert r.status_code == 200
        assert r.json()["name"] == "AvatarLoom Runtime Gateway"

    def test_health(self, gateway_server) -> None:
        import httpx

        host, port = gateway_server
        r = httpx.get(f"http://{host}:{port}/api/health", timeout=5)
        assert r.json()["status"] == "ok"


class TestGatewayWebSocket:
    async def test_start_session(self, gateway_server) -> None:
        host, port = gateway_server
        async with await _ws_connect(host, port) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "session.start",
                        "payload": {"profile_id": "mock"},
                    }
                )
            )
            # 找 session.started
            data = await _recv_until(ws, "session.started", timeout=5)
            assert data is not None
            assert data["payload"]["profile_id"] == "mock"

    async def test_ping_pong(self, gateway_server) -> None:
        host, port = gateway_server
        async with await _ws_connect(host, port) as ws:
            await ws.send(json.dumps({"type": "ping"}))
            data = await _recv_until(ws, "pong", timeout=5)
            assert data is not None

    async def test_audio_triggers_pipeline(self, gateway_server) -> None:
        """发音频 → 触发 Mock 全链路 → 收到 transcript/llm/tts。"""
        host, port = gateway_server
        async with await _ws_connect(host, port) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "session.start",
                        "payload": {"profile_id": "mock"},
                    }
                )
            )
            await _recv_until(ws, "session.started", timeout=5)

            # 发高能量音频触发 VAD
            loud = _make_pcm(1600, 28000)
            for _ in range(4):
                await ws.send(loud)
            # 静音触发 speech.ended
            silent = _make_pcm(1600, 0)
            for _ in range(5):
                await ws.send(silent)

            # 收事件
            types: set[str] = set()
            deadline = time.time() + 8
            while time.time() < deadline and not _has_pipeline_events(types):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    if isinstance(raw, bytes):
                        if raw[0] == 0x03:
                            types.add("tts.audio.binary")
                        elif raw[0] == 0x01:
                            types.add("avatar.frame.binary")
                    else:
                        data = json.loads(raw)
                        types.add(data.get("type", ""))
                except TimeoutError:
                    continue

            assert "transcript.completed" in types, f"缺 transcript，收到 {types}"
            assert "llm.text.delta" in types or "llm.text.done" in types
            assert "tts.audio.delta" in types or "tts.audio.binary" in types

    async def test_disconnect_cleans_up(self, gateway_server) -> None:
        """断开连接应清理资源（不发错就过）。"""
        host, port = gateway_server
        async with await _ws_connect(host, port) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "session.start",
                        "payload": {"profile_id": "mock"},
                    }
                )
            )
            await _recv_until(ws, "session.started", timeout=5)
        # 退出 with 自动 close


# ---- helpers ----


def _make_pcm(samples: int, amplitude: int) -> bytes:
    arr = np.full(samples, amplitude, dtype=np.int16)
    return arr.tobytes()


async def _recv_until(ws, msg_type: str, timeout: float = 5) -> dict | None:
    """循环收 JSON 消息直到指定 type 或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.time())
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


def _has_pipeline_events(types: set[str]) -> bool:
    return (
        "transcript.completed" in types
        and ("llm.text.delta" in types or "llm.text.done" in types)
        and ("tts.audio.delta" in types or "tts.audio.binary" in types)
    )
