"""blocks/_http_retry.post_with_retry 单测（TTS/STT/Vision 共用重试逻辑）。"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from blocks._http_retry import post_with_retry


class _Resp:
    def __init__(self, status: int = 200) -> None:
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=None, response=None  # type: ignore[arg-type]
            )


class _FlakyClient:
    """post 前N次抛传输错误，之后成功。"""

    def __init__(self, failures: list[Exception], resp: _Resp | None = None) -> None:
        self.failures = list(failures)
        self.resp = resp or _Resp()
        self.calls = 0

    async def post(self, url: str, **kwargs: Any) -> _Resp:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return self.resp


class TestRetry:
    async def test_succeeds_after_transient_errors(self, monkeypatch) -> None:
        async def _sleep_noop(_: float) -> None:
            return None

        monkeypatch.setattr("blocks._http_retry.asyncio.sleep", _sleep_noop)
        client = _FlakyClient(
            [httpx.ConnectError("net"), httpx.ReadTimeout("slow")]
        )
        resp = await post_with_retry(client, "http://x/v1")  # type: ignore[arg-type]
        assert resp is client.resp
        assert client.calls == 3

    async def test_raises_after_exhaustion(self, monkeypatch) -> None:
        async def _sleep_noop(_: float) -> None:
            return None

        monkeypatch.setattr("blocks._http_retry.asyncio.sleep", _sleep_noop)
        client = _FlakyClient([httpx.ConnectError("net")] * 5)
        with pytest.raises(httpx.ConnectError):
            await post_with_retry(client, "http://x/v1")  # type: ignore[arg-type]
        assert client.calls == 3  # 默认 3 次耗尽

    async def test_http_status_error_not_retried(self) -> None:
        # 4xx/5xx 不在传输错误家族——立即抛出，不重试
        client = _FlakyClient([], resp=_Resp(500))
        with pytest.raises(httpx.HTTPStatusError):
            await post_with_retry(client, "http://x/v1")  # type: ignore[arg-type]
        assert client.calls == 1

    async def test_first_try_success(self) -> None:
        client = _FlakyClient([])
        resp = await post_with_retry(client, "http://x/v1")  # type: ignore[arg-type]
        assert resp is client.resp
        assert client.calls == 1
