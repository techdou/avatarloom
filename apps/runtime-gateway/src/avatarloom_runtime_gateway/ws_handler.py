"""WebSocket 会话处理。

负责：
- 接收浏览器上行（JSON 控制 + 二进制 PCM）
- 转发 PCM 到 Orchestrator.ingest_audio
- 接收 Orchestrator emit 的事件，转发给浏览器（JSON + 二进制 PCM/JPEG）
- 管理会话生命周期

音频编码：PCM16/16kHz/单声道，base64 编码放 JSON payload.pcm_b64。
v0.1 用 JSON 承载音频（简化前端实现）；二进制通道留给 Avatar JPEG。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from avatarloom_protocol import (
    AVATAR_IDLE_FRAME,
    AVATAR_SPEECH_FRAME,
    AVATAR_VIDEO_READY,
    RESPONSE_DONE,
    RUN_STARTED,
    SESSION_STATE_CHANGED,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    VISION_REQUEST,
    VISION_RESULT,
    Event,
)
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from avatarloom_runtime_gateway.auth import (
    header_token_authenticated,
    token_matches,
)
from avatarloom_runtime_gateway.config import Settings
from avatarloom_runtime_gateway.protocol import (
    MAX_CAMERA_FRAME_BYTES,
    TAG_AVATAR_JPEG,
    TAG_CAMERA_FRAME,
    TAG_PCM_UPLINK,
    TAG_TTS_PCM_DOWNLINK,
    ClientMessage,
)
from runtime.orchestrator import Orchestrator
from runtime.orchestrator.config import BlockRef, OrchestratorConfig
from runtime.recorder import RunRecorder
from runtime.session import Session

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# profile_id / persona_id 白名单——两者都会拼进 workspace 下的文件路径
# （profiles/{id}.yaml、personas/{id}/），客户端可控，必须防路径穿越。
_ID_PATTERN = re.compile(r"[a-zA-Z0-9_-]{1,64}")

# GPU deployment 标识——这些 deployment 会初始化 CUDA context，会话结束后
# 需要自重启（rc=42）清除 fork-unsafe 的 CUDA 状态。mock/cpu 不触发。
_GPU_DEPLOYMENTS = frozenset({"cuda-local", "nvidia-cuda"})

# WS 上行消息大小上限——单条 JSON/二进制超此即拒绝，防内存 DoS
_MAX_MSG_SIZE = 2 * 1024 * 1024  # 2MB

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


# ------------------------------------------------------------------
# 模块级 helper
# ------------------------------------------------------------------


def _put_drop_oldest(q: asyncio.Queue[bytes], item: bytes) -> None:
    """非阻塞入队；队满丢最旧（音频跳段/视频跳帧，绝不反压事件出口）。"""
    if q.full():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        q.put_nowait(item)
    except asyncio.QueueFull:
        pass


class WebSocketSession:
    """单浏览器连接的 WS 会话。"""

    def __init__(self, ws: WebSocket, settings: Settings) -> None:
        self.ws = ws
        self.settings = settings
        self.orchestrator: Orchestrator | None = None
        self.session: Session | None = None
        self.recorder: RunRecorder | None = None
        # 下行三队列（AL-P2-006）：控制 / 音频 / 视频分离——
        # 此前单队列混排，队满无差别丢最旧，error/response.done 也会被丢；
        # 且 TTS/Avatar 阻塞 put 让慢客户端反压整个 Orchestrator 事件出口。
        self._control_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)
        # TTS PCM：32ms/块，64 块 ≈ 2s 缓冲；队满丢最旧（音频可跳段）
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
        # Avatar 帧：25fps，32 帧 ≈ 1.3s 缓冲；队满丢最旧（视频可跳帧）
        self._video_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
        self._downlink_task: asyncio.Task[None] | None = None
        self._closed = False
        self._warned_unknown_tag = False
        # 下行最近一次成功发送时间——90s idle 超时按下行活动顺延（AL-P2-007 修正）
        self._last_downlink_at = time.monotonic()
        # 是否装配了 GPU block——决定会话结束后是否需要自重启（rc=42）。
        # mock profile 全是 deployment="mock"，不触发；GPU profile 才触发。
        self._had_gpu_block: bool = False

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
            self._downlink_task = asyncio.create_task(self._downlink_sender())
            while not self._closed:
                try:
                    msg = await asyncio.wait_for(self.ws.receive(), timeout=90)
                except TimeoutError:
                    # 下行仍在持续（客户端在听/看但没上行）时不算 idle
                    if time.monotonic() - self._last_downlink_at < 90:
                        continue
                    logger.info("ws idle timeout (90s)——主动断开半开连接")
                    break
                if msg["type"] == "websocket.disconnect":
                    break
                if "text" in msg and msg["text"] is not None:
                    await self._handle_json(msg["text"])
                elif "bytes" in msg and msg["bytes"] is not None:
                    await self._handle_bytes(msg["bytes"])
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

    async def _handle_json(self, text: str) -> None:
        """处理上行 JSON 消息。"""
        # 消息大小上限——防止恶意客户端发超大 JSON 撑爆内存
        if len(text) > _MAX_MSG_SIZE:
            await self._send_error(f"message too large (max {_MAX_MSG_SIZE} bytes)")
            return
        try:
            data = json.loads(text)
            msg = ClientMessage(**data)
        except Exception as e:
            await self._send_error(f"invalid message: {e}")
            return

        if msg.type == "session.start":
            await self._start_session(msg.payload)
        elif msg.type == "session.stop":
            await self._stop_session()
        elif msg.type == "persona.set":
            await self._set_persona(msg.payload.get("persona_id"))
        elif msg.type == "audio.chunk":
            # PCM 在 payload.pcm_b64 里
            await self._handle_audio_chunk(msg.payload)
        elif msg.type == "audio.interrupt":
            await self._handle_interrupt()
        elif msg.type == "vision.frame_error":
            # 浏览器截帧失败（摄像头拒绝/不可用）→ 立即降级，不等 vision 超时
            await self._handle_vision_frame_error(msg.payload)
        elif msg.type == "ping":
            await self._enqueue_json({"type": "pong"})

    async def _handle_bytes(self, data: bytes) -> None:
        """处理上行二进制：显式 tag 路由（AL-P1-001）。

        0x00 + PCM16 → STT；0x02 + JPEG → Vision；未知 tag 拒绝。
        不再"其他一律 PCM"——裸 PCM 首字节可能恰为 0x02 被误送 Vision。
        """
        if not self.session or not self.orchestrator:
            return
        if not data:
            return
        # 二进制消息大小上限——防止超大帧撑爆内存
        if len(data) > _MAX_MSG_SIZE:
            logger.warning("ws binary message too large: %d bytes", len(data))
            return
        tag = data[0]

        if tag == TAG_PCM_UPLINK:
            pcm = data[1:]
            # 奇数字节/空 chunk 无法按 int16 解码，丢弃
            if len(pcm) < 2 or len(pcm) % 2 != 0:
                return
            samples = len(pcm) // 2
            pcm_b64 = base64.b64encode(pcm).decode("ascii")
            await self.orchestrator.ingest_audio(self.session, pcm_b64, samples)
            return

        if tag == TAG_CAMERA_FRAME:
            jpeg = data[1:]
            # AL-P1-011：大小 + JPEG SOI header 校验，防任意内容打远程 Vision API
            if len(jpeg) > MAX_CAMERA_FRAME_BYTES:
                logger.warning("camera frame too large: %d bytes, rejected", len(jpeg))
                await self._send_error(
                    f"camera frame too large ({len(jpeg)} > {MAX_CAMERA_FRAME_BYTES})"
                )
                return
            if not jpeg.startswith(b"\xff\xd8\xff"):
                logger.warning("camera frame is not JPEG (bad SOI), rejected")
                await self._send_error("camera frame is not a valid JPEG")
                return
            jpeg_b64 = base64.b64encode(jpeg).decode("ascii")
            await self.orchestrator.ingest_vision_frame(self.session, jpeg_b64)
            return

        # 未知 tag：拒绝。error JSON 每连接只发一次，避免旧前端裸 PCM 刷屏
        logger.warning("unknown uplink binary tag 0x%02x (%d bytes), rejected", tag, len(data))
        if not self._warned_unknown_tag:
            self._warned_unknown_tag = True
            await self._send_error(
                f"unknown binary tag 0x{tag:02x}——上行协议要求 0x00+PCM16 / 0x02+JPEG"
            )

    async def _handle_audio_chunk(self, payload: dict[str, Any]) -> None:
        """处理 audio.chunk JSON 消息（带 pcm_b64）。"""
        if not self.session or not self.orchestrator:
            return
        pcm_b64 = payload.get("pcm_b64", "")
        if not pcm_b64:
            return
        # samples 由服务端按解码长度计算，不信任客户端上报（防指标/时长误导）
        try:
            pcm = base64.b64decode(pcm_b64, validate=True)
        except Exception:
            await self._send_error("audio.chunk: invalid base64 pcm_b64")
            return
        if len(pcm) < 2 or len(pcm) % 2 != 0:
            await self._send_error("audio.chunk: PCM must be even-length int16")
            return
        samples = len(pcm) // 2
        await self.orchestrator.ingest_audio(self.session, pcm_b64, samples)

    async def _handle_interrupt(self) -> None:
        """显式打断。"""
        if not self.session or not self.orchestrator:
            return
        await self.orchestrator.handle_user_speech_started(self.session)

    async def _handle_vision_frame_error(self, payload: dict[str, Any]) -> None:
        """浏览器截帧失败——通知 Orchestrator 降级（唤醒同轮 Vision 等待）。"""
        if not self.session or not self.orchestrator:
            return
        reason = str(payload.get("reason") or "unknown")
        await self.orchestrator.handle_vision_frame_error(self.session, reason)

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
            await self._send_error(f"invalid profile_id: {profile_id!r}")
            return

        # persona_id 白名单校验——会拼进 personas/{id}/ 路径，同样防穿越
        if persona_id is not None and (
            not isinstance(persona_id, str) or not _ID_PATTERN.fullmatch(persona_id)
        ):
            await self._send_error(f"invalid persona_id: {persona_id!r}")
            return

        # 单会话强制（HIGH-4）：GPU 模型重复加载会 OOM，拒绝并存。
        # check + 占位原子化——否则两个连接都通过 None 检查后并发 setup，
        # 各自全量加载一套 GPU 模型（真实发生过的 OOM 路径）
        async with _session_lock:
            busy = _active_orchestrator is not None or _orchestrator_starting
            if not busy:
                _orchestrator_starting = True
        if busy:
            await self._send_error(
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
                    await self._send_error(f"profile 加载失败（{profile_id}），详见服务端日志")
                    return
            if config is None:
                config = _mock_profile_config()
                config.profile_id = profile_id

            # Recorder 接收所有事件
            recorder = RunRecorder(root=self.settings.runs_root)
            orchestrator = Orchestrator(
                config,
                event_sink=self._on_orchestrator_event,
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
                await self._send_error("orchestrator 初始化失败，详见服务端日志")
                return

            # 全部就绪后原子登记（锁内 set，与上面的 check 配对）
            async with _session_lock:
                _active_orchestrator = orchestrator
            self.recorder = recorder
            self.orchestrator = orchestrator
            self.session = session
            # 标记是否装配了 GPU block——用于会话结束后判定是否自重启。
            # fallback 降级后的 deployment 也算（如 flashhead→musetalk 仍 cuda-local），
            # 但 orchestrator.blocks 存的是实例不含 deployment；这里看 config 的原始声明，
            # 若任一 block 的 deployment 标记为 GPU，保守视为 GPU 会话。
            self._had_gpu_block = any(
                ref.deployment in _GPU_DEPLOYMENTS for ref in config.blocks.values()
            )
        finally:
            async with _session_lock:
                _orchestrator_starting = False

        await self._enqueue_json(
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
            await self._send_error("persona.set 需要先建立会话（session.start）")
            return
        # persona_id 白名单校验——会拼进 personas/{id}/ 路径，防路径穿越
        if not persona_id or not _ID_PATTERN.fullmatch(persona_id):
            await self._send_error(f"invalid persona_id: {persona_id!r}")
            return
        try:
            from blocks.persona.loader import load_persona

            workspace = Path(self.settings.workspace_root)
            persona = load_persona(workspace / "personas" / persona_id, workspace_root=str(workspace))
            await self.orchestrator.switch_persona(self.session, persona)
        except Exception:
            # 对外脱敏：异常原文（含服务器路径/persona 包内部结构）只进服务端日志
            logger.exception("persona.set %s failed", persona_id)
            await self._send_error(f"persona 切换失败（{persona_id}），详见服务端日志")
            return
        await self._enqueue_json(
            {
                "type": "persona.changed",
                "payload": {"persona_id": persona_id},
            }
        )

    # ------------------------------------------------------------------
    # Orchestrator 事件 -> 浏览器
    # ------------------------------------------------------------------

    async def _on_orchestrator_event(self, event: Event) -> None:
        """Orchestrator emit 的事件出口——转发给浏览器。

        - session.* / transcript.* / llm.* / response.* → JSON 下行
        - tts.audio.delta → 二进制 PCM 下行（tag + PCM）+ JSON 元数据
        - avatar.*_frame → 二进制 JPEG 下行（tag + JPEG）+ JSON 元数据
        """
        # 新一轮 Run：在 record() 之前 start_run，保证后续（含本事件）都被记录
        if (
            event.type == RUN_STARTED
            and self.recorder
            and event.run_id
            and not self.recorder.is_active(event.run_id)
        ):
            await self.recorder.start_run(
                event.run_id,
                event.session_id,
                self.session.profile_id if self.session else "mock",
                persona_id=self.session.persona_id if self.session else None,
            )

        # Recorder 记录
        if self.recorder and event.run_id:
            await self.recorder.record(event)

        # 状态变更/会话事件
        if event.type == SESSION_STATE_CHANGED:
            await self._enqueue_json(
                {
                    "type": "session.state_changed",
                    "payload": event.payload,
                }
            )
        elif event.type == "session.started":
            await self._enqueue_json({"type": "session.started", "payload": event.payload})
        elif event.type == TRANSCRIPT_COMPLETED:
            await self._enqueue_json(
                {
                    "type": "transcript.completed",
                    "payload": event.payload,
                }
            )
        elif event.type == RUN_STARTED:
            # 通知前端新 Run 开始（Recorder 已在上方的 start_run 早启动逻辑里就绪）
            await self._enqueue_json({"type": "run.started", "payload": event.payload})
        elif event.type == "llm.text.delta":
            await self._enqueue_json({"type": "llm.text.delta", "payload": event.payload})
        elif event.type == "llm.text.done":
            await self._enqueue_json({"type": "llm.text.done", "payload": event.payload})
        elif event.type == RESPONSE_DONE:
            await self._enqueue_json({"type": "response.done", "payload": event.payload})
            # 结束 Run 记录
            if self.recorder and event.run_id and self.recorder.is_active(event.run_id):
                await self.recorder.finalize_run(event.run_id)

        # Vision：触发词命中 → 请求浏览器截帧；分析结果 → 下行描述
        elif event.type == VISION_REQUEST:
            await self._enqueue_json({"type": "vision.request", "payload": event.payload})
        elif event.type == VISION_RESULT:
            await self._enqueue_json({"type": "vision.result", "payload": event.payload})

        # TTS 音频：二进制下行 + JSON 元数据
        elif event.type == TTS_AUDIO_DELTA:
            pcm_b64 = event.payload.get("pcm_b64", "")
            if pcm_b64:
                try:
                    pcm = base64.b64decode(pcm_b64)
                    # 下行格式：0x03 + PCM；音频队列非阻塞丢最旧（不反压事件出口）
                    _put_drop_oldest(self._audio_queue, bytes([TAG_TTS_PCM_DOWNLINK]) + pcm)
                except Exception:
                    logger.warning("TTS audio base64 decode failed——audio chunk dropped", exc_info=True)
            # 元数据（不含 pcm_b64，减小 JSON 体积）——控制队列，不丢
            meta = {k: v for k, v in event.payload.items() if k != "pcm_b64"}
            await self._enqueue_json({"type": "tts.audio.delta", "payload": meta})

        elif event.type == TTS_AUDIO_COMPLETED:
            await self._enqueue_json({"type": "tts.audio.completed", "payload": event.payload})

        elif event.type == AVATAR_VIDEO_READY:
            await self._enqueue_json(
                {"type": "avatar.video.ready", "payload": event.payload}
            )

        # Avatar 帧：二进制下行
        elif event.type in (AVATAR_SPEECH_FRAME, AVATAR_IDLE_FRAME):
            frame_b64 = event.payload.get("frame_b64", "")
            if frame_b64:
                try:
                    jpeg = base64.b64decode(frame_b64)
                    # 下行格式：0x01 + 0x00/0x01(子tag) + JPEG；视频队列丢最旧
                    sub_tag = 0x01 if event.type == AVATAR_SPEECH_FRAME else 0x00
                    _put_drop_oldest(self._video_queue, bytes([TAG_AVATAR_JPEG, sub_tag]) + jpeg)
                except Exception:
                    logger.warning("avatar frame base64 decode failed——frame dropped", exc_info=True)

    async def _downlink_sender(self) -> None:
        """独立任务：三队列优先级调度发送（控制 > 音频 > 视频）。

        每轮从 control 开始轮询，发一条即重排——控制事件绝对优先；
        全空时 5ms 短睡眠（25fps 帧间隔 40ms，无感）。避免阻塞 Orchestrator。
        """
        try:
            while not self._closed:
                sent = False
                # 控制队列（JSON）
                try:
                    ctrl = self._control_queue.get_nowait()
                    if self.ws.client_state != WebSocketState.CONNECTED:
                        break

                    await self.ws.send_text(json.dumps(ctrl, ensure_ascii=False))
                    sent = True
                    self._last_downlink_at = time.monotonic()
                except asyncio.QueueEmpty:
                    pass
                # 音频队列
                if not sent:
                    try:
                        audio = self._audio_queue.get_nowait()
                        if self.ws.client_state != WebSocketState.CONNECTED:
                            break
                        await self.ws.send_bytes(audio)
                        sent = True
                        self._last_downlink_at = time.monotonic()
                    except asyncio.QueueEmpty:
                        pass
                # 视频队列
                if not sent:
                    try:
                        video = self._video_queue.get_nowait()
                        if self.ws.client_state != WebSocketState.CONNECTED:
                            break
                        await self.ws.send_bytes(video)
                        sent = True
                        self._last_downlink_at = time.monotonic()
                    except asyncio.QueueEmpty:
                        pass
                if not sent:
                    await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("downlink send error")

    async def _enqueue_json(self, data: dict[str, Any]) -> None:
        """入队 JSON 控制消息（AL-P2-006）。

        控制事件量小（状态/错误/边界），512 深度几乎不会满；
        真满说明客户端已不消费——短等待（2s）后丢弃并告警，
        避免慢客户端反压整个 Orchestrator 事件出口（含 recorder/TTS 链路）。
        """
        try:
            self._control_queue.put_nowait(data)
        except asyncio.QueueFull:
            try:
                await asyncio.wait_for(self._control_queue.put(data), timeout=2.0)
            except TimeoutError:
                logger.warning(
                    "control queue full for 2s——dropping JSON message %s",
                    data.get("type"),
                )

    async def _send_error(self, message: str) -> None:
        await self._enqueue_json({"type": "error", "payload": {"message": message}})

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    async def cleanup(self) -> None:
        """清理会话资源。"""
        global _active_orchestrator

        if self._closed:
            return
        self._closed = True

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

        # 收尾 Recorder：flush 所有未 finalize 的 Run（events.jsonl 文件句柄、
        # metrics/transcript 落盘），避免客户端断开时资源泄漏。
        if self.recorder:
            try:
                await self.recorder.shutdown()
            except Exception:
                logger.exception("recorder shutdown error")

        if self._downlink_task:
            self._downlink_task.cancel()
            try:
                await self._downlink_task
            except asyncio.CancelledError:
                pass

        had_gpu_session = self._had_gpu_block
        self.orchestrator = None
        self.session = None
        self.recorder = None
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
