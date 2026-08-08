"""Runtime Gateway 启动入口。"""

from __future__ import annotations

import uvicorn

from avatarloom_runtime_gateway.config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "avatarloom_runtime_gateway.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level.lower(),
        # 禁用协议层 keepalive ping：装配期间（60-90s）阻塞式 session.start 不回
        # pong 会让双方 keepalive 双双超时断开；保活交给应用层消息心跳
        # （前端 20s ping 消息 / 服务端 90s idle 超时）。
        ws_ping_interval=None,
        ws_ping_timeout=None,
    )


if __name__ == "__main__":
    main()
