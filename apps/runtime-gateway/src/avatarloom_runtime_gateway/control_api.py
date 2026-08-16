"""Control API 上报客户端——Session/Run 生命周期写回 DB。

Studio 的 Runs/Sessions 页面数据源是 control-api 的 DB 表；真实运行数据
原本只落在 runs_root 文件系统（RunRecorder），DB 表没有生产者。本模块在
gateway 侧补上这条上报链：

- WebSocketSession._start_session 成功 → POST /sessions
- WebSocketSession.cleanup → PATCH /sessions/{id}（status=ended）
- event_bridge 收到 RUN_STARTED → POST /runs
- event_bridge 收到 RESPONSE_DONE（recorder finalize 后）→ PATCH /runs/{id}
  （带 metrics/transcript，读自 recorder 落盘产物）

失败策略：全部静默降级（log warning）——上报是旁路，绝不阻塞 WS 会话
主链路；control-api 不可达时对话照常，只是 Runs/Sessions 页缺记录。
POST 用 upsert 语义（control-api 端幂等），重试安全。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from avatarloom_runtime_gateway.config import Settings, control_api_auth_headers

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ControlApiReporter:
    """向 control-api 上报 Session/Run 生命周期（fire-and-forget，失败仅日志）。"""

    def __init__(self, settings: Settings) -> None:
        base = settings.control_api_url.rstrip("/")
        # control_api_url 不带 /api 后缀（如 http://127.0.0.1:8100）
        self._base_url = base if base.endswith("/api") else f"{base}/api"
        self._headers = control_api_auth_headers(settings)
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers,
                timeout=5.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _request(self, method: str, path: str, payload: dict[str, Any]) -> None:
        try:
            client = await self._ensure_client()
            r = await client.request(method, path, json=payload)
            r.raise_for_status()
        except Exception:
            logger.warning("control-api 上报失败 %s %s", method, path, exc_info=True)

    # ------------------------------------------------------------------
    # Session 生命周期
    # ------------------------------------------------------------------

    async def report_session_started(
        self,
        session_id: str,
        *,
        profile_id: str | None,
        persona_id: str | None,
    ) -> None:
        await self._request(
            "POST",
            "/sessions",
            {
                "id": session_id,
                "profile_id": profile_id,
                "persona_id": persona_id,
                "status": "active",
            },
        )

    async def report_session_ended(self, session_id: str, *, status: str = "closed") -> None:
        await self._request(
            "PATCH",
            f"/sessions/{session_id}",
            {"status": status, "ended_at": _now_iso()},
        )

    # ------------------------------------------------------------------
    # Run 生命周期
    # ------------------------------------------------------------------

    async def report_run_started(
        self,
        run_id: str,
        *,
        session_id: str,
        profile_id: str | None,
        persona_id: str | None,
        run_dir: str | None = None,
    ) -> None:
        # run_dir 只上报目录名（= run_id），不含服务器绝对路径
        await self._request(
            "POST",
            "/runs",
            {
                "id": run_id,
                "session_id": session_id,
                "profile_id": profile_id,
                "persona_id": persona_id,
                "status": "running",
                "run_dir": run_id,
            },
        )

    async def report_run_finalized(
        self,
        run_id: str,
        *,
        status: str,
        metrics: dict[str, Any] | None = None,
        user_text: str | None = None,
        assistant_text: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"status": status, "ended_at": _now_iso()}
        if metrics is not None:
            payload["metrics"] = metrics
        if user_text is not None:
            payload["user_text"] = user_text
        if assistant_text is not None:
            payload["assistant_text"] = assistant_text
        await self._request("PATCH", f"/runs/{run_id}", payload)
