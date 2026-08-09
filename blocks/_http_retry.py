"""共享 HTTP 重试 helper。

TTS/STT/Vision 的 OpenAI 兼容 block 此前各自单次失败即放弃，
与 LLM block 的 ReadError/RemoteProtocolError 三次退避重试不一致。
统一用此 helper，AutoDL 出网抖动时不再丢整句音频/识别。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 与 LLM block 一致的重试参数
_MAX_RETRIES = 3
_BASE_DELAY = 0.5


async def post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    max_retries: int = _MAX_RETRIES,
) -> httpx.Response:
    """带重试的 POST——对连接级/传输级错误退避重试，HTTP 状态错误直接返回。

    重试覆盖：ConnectTimeout / ConnectError / ReadTimeout / ReadError /
    RemoteProtocolError（AutoDL 出网抖动的全家族）。
    4xx/5xx 不重试（服务端错误重试无意义）。
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = await client.post(url, json=json, files=files, data=data)
            resp.raise_for_status()
            return resp
        except (
            httpx.ConnectTimeout,
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.ReadError,
            httpx.RemoteProtocolError,
        ) as e:
            last_exc = e
            if attempt < max_retries - 1:
                delay = _BASE_DELAY * (attempt + 1)
                logger.warning(
                    "HTTP retry %d/%d for %s: %s (waiting %.1fs)",
                    attempt + 1,
                    max_retries,
                    url,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                raise
    # 不应到达——循环内要么 return 要么 raise
    raise last_exc  # type: ignore[misc]
