"""pytest 全局 fixtures 和配置。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

# 让 pytest-asyncio 的 event_loop scope 跟 session 一致，避免跨 fixture 警告。
# pytest-asyncio 1.x 默认 strict mode，需显式声明。


@pytest.fixture(scope="session")
def event_loop() -> AsyncIterator[asyncio.AbstractEventLoop]:
    """会话级 event loop，跨 fixture 复用。"""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    """每个测试用独立临时工作目录，避免污染。"""
    return tmp_path
