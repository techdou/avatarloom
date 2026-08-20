"""WebSocket 会话处理。

负责：
- 接收浏览器上行（JSON 控制 + 二进制 PCM）
- 转发 PCM 到 Orchestrator.ingest_audio
- 接收 Orchestrator emit 的事件，转发给浏览器（JSON + 二进制 PCM/JPEG）
- 管理会话生命周期（鉴权 / 单会话锁 / GPU 自重启）

模块组成：
- ``ws_handler``（本文件）：WebSocketSession 主循环 + 鉴权 + 生命周期 + 进程级
  单会话锁 + GPU 自重启。持有 UplinkDispatcher 和 OrchestratorEventBridge 实例。
- ``uplink``：上行 JSON/二进制消息分发（表驱动路由）
- ``event_bridge``：Orchestrator 事件 → 三队列下行调度（控制 > 音频 > 视频）

音频编码：PCM16/16kHz/单声道，base64 编码放 JSON payload.pcm_b64。
v0.1 用 JSON 承载音频（简化前端实现）；二进制通道留给 Avatar JPEG。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from avatarloom_runtime_gateway.auth import (
    header_token_authenticated,
    token_matches,
)
from avatarloom_runtime_gateway.config import Settings
from avatarloom_runtime_gateway.control_api import ControlApiReporter
from avatarloom_runtime_gateway.event_bridge import OrchestratorEventBridge, put_drop_oldest
from avatarloom_runtime_gateway.uplink import UplinkDispatcher
from runtime.orchestrator import Orchestrator
from runtime.orchestrator.config import BlockRef, OrchestratorConfig
from runtime.recorder import RunRecorder
from runtime.session import Session

# 向后兼容 re-export：旧测试 (test_gateway_ws.py:375) 直接 from ws_handler import _put_drop_oldest
_put_drop_oldest = put_drop_oldest

logger = logging.getLogger(__name__)

# profile_id / persona_id 白名单——两者都会拼进 workspace 下的文件路径
# （profiles/{id}.yaml、personas/{id}/），客户端可控，必须防路径穿越。
_ID_PATTERN = re.compile(r"[a-zA-Z0-9_-]{1,64}")

# GPU deployment 标识——这些 deployment 会初始化 CUDA context，会话结束后
# 需要自重启（rc=42）清除 fork-unsafe 的 CUDA 状态。mock/cpu 不触发。
_GPU_DEPLOYMENTS = frozenset({"cuda-local", "nvidia-cuda"})

# GPU 会话结束后是否自重启（rc=42）：默认开启，依赖 supervisor/dev.py 拉起；
# 无 supervisor 的部署可设 AVATARLOOM_SELF_RESTART=0 关闭（需手动重启清 CUDA 状态）。
_SELF_RESTART = os.environ.get("AVATARLOOM_SELF_RESTART", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# 进程级活跃会话锁（HIGH-4）：GPU profile 每套模型占 ~10-16G，多标签/重复连接
# 并存会直接 OOM。session.mode=single 只在 profile 里声明，这里强制执行——
# 已有活跃 orchestrator 时拒绝新会话，前端刷新会先断开旧连接（cleanup 释放）。
_active_orchestrator: Orchestrator | None = None
# setup 占位标记：orchestrator.setup() 要加载 GPU 模型（秒~分钟级），
# 仅在登记 _active_orchestrator 时才拦截会让并发连接双双穿透检查、各加载一套模型。
# check + 占位必须在 _session_lock 内原子完成。
_orchestrator_starting: bool = False
_session_lock = asyncio.Lock()


def get_active_orchestrator() -> Orchestrator | None:
    """返回当前活跃的 Orchestrator（供 HTTP 管理端点读取运行时状态）。"""
    return _active_orchestrator


# Mock Profile 默认配置（无 GPU/API Key 也能跑）
def _mock_profile_config() -> OrchestratorConfig:
    return OrchestratorConfig(
        profile_id="mock",
        blocks={
            "vad": BlockRef(
                id="vad.mock",
                deployment="mock",
                config={
                    "energy_threshold": 300.0,
                    "min_speech_chunks": 2,
                    "silence_chunks_to_end": 3,
                },
            ),
            "stt": BlockRef(id="stt.mock", deployment="mock"),
            "llm": BlockRef(id="llm.mock", deployment="mock", config={"chunk_delay_ms": 30}),
            "tts": BlockRef(id="tts.mock", deployment="mock", config={"ms_per_char": 50}),
            "avatar": BlockRef(id="avatar.mock", deployment="mock"),
        },
    )


class WebSocketSession:
    """单浏览器连接的 WS 会话。

    职责（拆分后保留的部分）：
    - ``run()`` 主循环：auth → receive loop → cleanup
    - ``_authenticate()``：握手后首条 auth 消息鉴权
    - 会话生命周期：``_start_session`` / ``_stop_session`` / ``set_persona`` / ``cleanup``
    - 进程级单会话锁 + GPU 自重启（rc=42）
    - 持有 ``UplinkDispatcher`` 和 ``OrchestratorEventBridge`` 实例

    上行消息分发委托给 ``self._dispatcher``（见 uplink.py）；
    下行三队列调度委托给 ``self.bridge``（见 event_bridge.py）。
    """

    def __init__(self, ws: WebSocket, settings: Settings) -> None:
        self.ws = ws
        self.settings = settings
        self.orchestrator: Orchestrator | None = None
        self.session: Session | None = None

        # 下行事件桥接（三队列 + recorder）——is_closed 回调避免循环引用
        self.bridge = OrchestratorEventBridge(ws, is_closed=lambda: self._closed)
        # Session/Run 生命周期上报 control-api（Runs/Sessions 页数据源；失败仅日志）
        self.reporter = ControlApiReporter(settings)
        self.bridge.reporter = self.reporter
        # 上行消息分发——session 自身满足 UplinkContext Protocol
        self._dispatcher = UplinkDispatcher(ctx=self)

        self._closed = False
        # 是否装配了 GPU block——决定会话结束后是否需要自重启（rc=42）。
        # mock profile 全是 deployment="mock"，不触发；GPU profile 才触发。
        self._had_gpu_block: bool = False

    # ------------------------------------------------------------------
    # UplinkContext Protocol 实现——供 UplinkDispatcher 调用
    # ------------------------------------------------------------------
    # dispatcher 通过这些方法访问 session 状态与生命周期，避免在 uplink.py
    # 直接 import WebSocketSession 造成循环依赖。

    async def start_session(self, payload: dict[str, Any]) -> None:
        await self._start_session(payload)

    async def stop_session(self) -> None:
        await self._stop_session()

    async def set_persona(self, persona_id: str | None) -> None:
        await self._set_persona(persona_id)

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """主循环：接收上行消息，处理控制 + 音频。

        90s idle 超时（AL-P2-007）：半开连接（断网未发 FIN）不再永久悬挂——
        前端 20s ping 保活，正常连接不会触发；超时主动断开走 cleanup。
        """
        try:
            # 浏览器不能设置 Authorization：token 开启时，握手后必须先发一次
            # {"type":"auth","token":"..."}，通过后才允许创建会话/装载模型。
            if not await self._authenticate():
                return

            # 启动下行发送任务
            self.bridge.start()
            while not self._closed:
                try:
                    msg = await asyncio.wait_for(self.ws.receive(), timeout=90)
                except TimeoutError:
                    # 下行仍在持续（客户端在听/看但没上行）时不算 idle
                    if time.monotonic() - self.bridge.last_downlink_at < 90:
                        continue
                    logger.info("ws idle timeout (90s)——主动断开半开连接")
                    break
                if msg["type"] == "websocket.disconnect":
                    break
                if "text" in msg and msg["text"] is not None:
                    await self._dispatcher.handle_json(msg["text"])
                elif "bytes" in msg and msg["bytes"] is not None:
                    await self._dispatcher.handle_bytes(msg["bytes"])
        except WebSocketDisconnect:
            pass
        finally:
            await self.cleanup()

    async def _authenticate(self) -> bool:
        """完成浏览器首条 auth 消息鉴权；仅显式开发模式放行空 token。"""
        expected = self.settings.api_token.strip()
        if not expected:
            if self.settings.auth_disabled:
                return True
            await self.ws.close(code=1008)
            return False
        # 握手 Bearer 必须真验值（纵深防御：即使入口未走 verify_ws_access 也成立）
        if header_token_authenticated(self.ws, self.settings):
            return True

        try:
            message = await asyncio.wait_for(self.ws.receive(), timeout=10)
        except (TimeoutError, WebSocketDisconnect):
            logger.warning("ws auth timeout/disconnect")
            await self.ws.close(code=1008)
            return False
        if message.get("type") != "websocket.receive" or not message.get("text"):
            await self.ws.close(code=1008)
            return False
        try:
            data = json.loads(message["text"])
        except (TypeError, json.JSONDecodeError):
            await self.ws.close(code=1008)
            return False
        token = data.get("token") if data.get("type") == "auth" else None
        if not isinstance(token, str) or not token_matches(token.strip(), expected):
            logger.warning("ws rejected: invalid auth message")
            await self.ws.close(code=1008)
            return False
        return True

    # ------------------------------------------------------------------
    # 会话生命周期
    # ------------------------------------------------------------------

    async def _start_session(self, payload: dict[str, Any]) -> None:
        """启动新会话。"""
        global _active_orchestrator, _orchestrator_starting

        profile_id = payload.get("profile_id") or self.settings.default_profile
        persona_id = payload.get("persona_id")

        # profile_id 白名单校验——客户端可控，防路径穿越（../../ 读任意 yaml）
        if not isinstance(profile_id, str) or not _ID_PATTERN.fullmatch(profile_id):
            await self.bridge.send_error(f"invalid profile_id: {profile_id!r}")
            return

        # persona_id 白名单校验——会拼进 personas/{id}/ 路径，同样防穿越
        if persona_id is not None and (
            not isinstance(persona_id, str) or not _ID_PATTERN.fullmatch(persona_id)
        ):
            await self.bridge.send_error(f"invalid persona_id: {persona_id!r}")
            return

        # 单会话强制（HIGH-4）：GPU 模型重复加载会 OOM，拒绝并存。
        # check + 占位原子化——否则两个连接都通过 None 检查后并发 setup，
        # 各自全量加载一套 GPU 模型（真实发生过的 OOM 路径）
        async with _session_lock:
            busy = _active_orchestrator is not None or _orchestrator_starting
            if not busy:
                _orchestrator_starting = True
        if busy:
            await self.bridge.send_error(
                "已有活跃会话，请先关闭/刷新页面（旧会话断开后模型会释放）"
            )
            return

        try:
            # v0.1：默认用 Mock profile（profile 加载逻辑在阶段 9 完善）
            config = None
            profiles_dir = Path(self.settings.workspace_root) / "profiles"
            profile_path = profiles_dir / f"{profile_id}.yaml"
            if profile_path.exists():
                try:
                    from runtime.orchestrator.profile_loader import load_profile

                    config = load_profile(profile_path)
                except Exception:
                    # 对外脱敏：异常原文（含服务器绝对路径/内部细节）只进服务端日志
                    logger.exception("profile %s load failed", profile_id)
                    await self.bridge.send_error(f"profile 加载失败（{profile_id}），详见服务端日志")
                    return
            if config is None:
                config = _mock_profile_config()
                config.profile_id = profile_id

            # Recorder 接收所有事件——注入 bridge（事件出口用它记录）
            recorder = RunRecorder(root=self.settings.runs_root)
            orchestrator = Orchestrator(
                config,
                event_sink=self.bridge.on_orchestrator_event,
            )
            try:
                await orchestrator.setup()
                session = await orchestrator.start_session(
                    persona_id=persona_id,
                    workspace_root=self.settings.workspace_root,
                )
            except asyncio.CancelledError:
                # 外部取消（服务关停）中途打断 setup——先回收已装配的模型再透传
                try:
                    await orchestrator.shutdown()
                except Exception:
                    logger.exception("setup 取消后 orchestrator 回收异常")
                raise
            except Exception:
                # setup/start 失败回收：已部分装配的 block/模型必须 shutdown 释放
                # （否则显存泄漏 + 占位卡死后续所有重试），再回错给客户端
                try:
                    await orchestrator.shutdown()
                except Exception:
                    logger.exception("setup 失败后 orchestrator 回收异常")
                # 对外脱敏：异常原文只进服务端日志
                logger.exception("orchestrator setup/start failed (profile=%s)", profile_id)
                await self.bridge.send_error("orchestrator 初始化失败，详见服务端日志")
                return

            # 全部就绪后原子登记（锁内 set，与上面的 check 配对）
            async with _session_lock:
                _active_orchestrator = orchestrator
            # 把 recorder / session 注入 bridge——之后 orchestrator emit 的事件
            # 会经 bridge.on_orchestrator_event 记录并下行
            self.bridge.recorder = recorder
            self.bridge.session_ref = session
            self.orchestrator = orchestrator
            self.session = session
            # 标记是否装配了 GPU block——用于会话结束后判定是否自重启。
            # fallback 降级后的 deployment 也算（如 flashhead→musetalk 仍 cuda-local），
            # 但 orchestrator.blocks 存的是实例不含 deployment；这里看 config 的原始声明，
            # 若任一 block 的 deployment 标记为 GPU，保守视为 GPU 会话。
            # 现有 profile 惯用 deployment: local + config.device: cuda 表达 GPU 本地
            # 部署——只认 deployment 集合会漏判，rc=42 从不触发，断线重连后
            # CUDA 污染进程 fork worker 必 SIGSEGV（avatar 永久降级 static 的根因）。
            self._had_gpu_block = any(
                ref.deployment in _GPU_DEPLOYMENTS
                or str(ref.config.get("device", "")).startswith("cuda")
                for ref in config.blocks.values()
            )
        finally:
            async with _session_lock:
                _orchestrator_starting = False

        await self.bridge.enqueue_json(
            {
                "type": "session.started",
                "payload": {
                    "session_id": self.session.session_id,
                    "profile_id": profile_id,
                    "persona_id": persona_id,
                    "state": self.session.state.value,
                    # 降级可见（AL-xxx）：block 装配失败走 fallback 时前端要能看到，
                    # 否则 TTS 静默降级 mock（440Hz 正弦波）用户只听到"电流声"
                    "degraded": orchestrator.degraded_blocks,
                },
            }
        )
        # Session 生命周期上报 control-api（旁路，失败仅日志不阻塞会话）
        await self.reporter.report_session_started(
            self.session.session_id,
            profile_id=profile_id,
            persona_id=persona_id,
        )
        logger.info("ws session started: %s (profile=%s)", self.session.session_id, profile_id)

    async def _stop_session(self) -> None:
        """停止会话。"""
        await self.cleanup()

    async def _set_persona(self, persona_id: str | None) -> None:
        """切换 Persona（AL-P1-004）：加载并调用 orchestrator.switch_persona()。

        此前只改 session.persona_id 就发 persona.changed——假切换：
        LLM prompt / TTS voice ref / Avatar portrait / memory namespace 都不同步。
        现在真切换成功才发 changed；加载/切换失败回明确 error。
        """
        if not self.session or not self.orchestrator:
            await self.bridge.send_error("persona.set 需要先建立会话（session.start）")
            return
        # persona_id 白名单校验——会拼进 personas/{id}/ 路径，防路径穿越
        if not persona_id or not _ID_PATTERN.fullmatch(persona_id):
            await self.bridge.send_error(f"invalid persona_id: {persona_id!r}")
            return
        try:
            from blocks.persona.loader import load_persona

            workspace = Path(self.settings.workspace_root)
            persona = load_persona(workspace / "personas" / persona_id, workspace_root=str(workspace))
            await self.orchestrator.switch_persona(self.session, persona)
        except Exception:
            # 对外脱敏：异常原文（含服务器路径/persona 包内部结构）只进服务端日志
            logger.exception("persona.set %s failed", persona_id)
            await self.bridge.send_error(f"persona 切换失败（{persona_id}），详见服务端日志")
            return
        await self.bridge.enqueue_json(
            {
                "type": "persona.changed",
                "payload": {"persona_id": persona_id},
            }
        )

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    async def cleanup(self) -> None:
        """清理会话资源。"""
        global _active_orchestrator

        if self._closed:
            return
        self._closed = True

        session_id = self.session.session_id if self.session else None

        if self.session and self.orchestrator:
            try:
                await self.orchestrator.end_session(self.session, reason="client_disconnect")
            except Exception:
                logger.exception("end_session error")

        if self.orchestrator:
            try:
                await self.orchestrator.shutdown()
            except Exception:
                logger.exception("orchestrator shutdown error")
            finally:
                # 单会话锁在 shutdown 完成后才释放（HIGH-4 根因：先释放会让新会话
                # 在旧模型 VRAM 未清时并发加载 → 瞬态双份占用 → OOM）
                async with _session_lock:
                    if _active_orchestrator is self.orchestrator:
                        _active_orchestrator = None

        # 收尾 bridge：cancel downlink task + flush recorder（events.jsonl 句柄、
        # metrics/transcript 落盘），并对未收到 response.done 的 run 兜底上报
        # interrupted。之后再上报 session 收尾（此时 run 旁路已 drain）。
        await self.bridge.stop()
        if session_id:
            await self.reporter.report_session_ended(session_id)
            await self.reporter.close()

        had_gpu_session = self._had_gpu_block
        self.orchestrator = None
        self.session = None
        self.bridge.session_ref = None
        self.bridge.reporter = None
        self._had_gpu_block = False

        if had_gpu_session and not os.environ.get("AVATARLOOM_TESTING") and _SELF_RESTART:
            # 真实会话结束 → 本进程自重启（退出码 42，supervisor 拉起）。
            # 根因：gateway 进程一旦初始化 CUDA context（加载过任何 GPU 模型），
            # 之后 fork 任何子进程（MuseTalk worker）都会 SIGSEGV——NV 驱动在
            # fork 后（exec 前）的 atfork 清理与活跃 CUDA context 冲突。
            # 新进程无 CUDA context，avatar 首位装配（fork 在 GPU 加载前）即安全。
            # 模型与显存已在上面 shutdown 释放；os._exit 跳过 uvicorn 收尾直接退出。
            logger.info("ws session cleaned, self-restarting (rc=42) for clean CUDA state")
            os._exit(42)
        if had_gpu_session and not os.environ.get("AVATARLOOM_TESTING"):
            logger.warning(
                "GPU session cleaned but AVATARLOOM_SELF_RESTART=0——"
                "CUDA state may be stale; restart gateway manually before next GPU session"
            )
