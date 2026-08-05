"""Orchestrator 主类。

核心职责：
1. 装配 Block（从 OrchestratorConfig）
2. EventBus 订阅连成主链路
3. 驱动 Session 状态机响应各类事件
4. 双写 TTS audio delta → browser + avatar
5. Block 失败时降级（avatar/vision 缺席不阻断语音）
6. 打断处理

主链路事件流：
    audio.appended (browser)
        -> VAD -> speech.detected/ended
        -> STT -> transcript.completed
        -> LLM -> llm.text.delta/done
        -> TTS -> tts.audio.delta/completed
        -> Avatar -> avatar.speech_frame/idle_frame
        -> browser（双写：TTS audio 也直发浏览器播放）
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from avatarloom_protocol import (
    AUDIO_APPENDED,
    LLM_TEXT_DELTA,
    SPEECH_DETECTED,
    SPEECH_ENDED,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_COMPLETED,
    Event,
    State,
)
from avatarloom_sdk import (
    Block,
    BlockContext,
    BlockError,
    BlockSetupError,
)

from runtime.event_bus import BackpressurePolicy, EventBus
from runtime.orchestrator.config import OrchestratorConfig
from runtime.session import Session, SessionManager

logger = logging.getLogger(__name__)


# Block category 标准名（和 Profile yaml 的 key 对齐）
CATEGORY_VAD = "vad"
CATEGORY_STT = "stt"
CATEGORY_LLM = "llm"
CATEGORY_TTS = "tts"
CATEGORY_AVATAR = "avatar"
CATEGORY_VISION = "vision"


# Block ID -> entrypoint 映射。v0.1 用 Mock 全部注册。
# 真实 Adapter 在阶段 5/6/8 增补。
BLOCK_REGISTRY: dict[str, str] = {
    "vad.mock": "blocks.vad.mock:MockVadBlock",
    "stt.mock": "blocks.stt.mock:MockSttBlock",
    "llm.mock": "blocks.llm.mock:MockLlmBlock",
    "tts.mock": "blocks.tts.mock:MockTtsBlock",
    "avatar.mock": "blocks.avatar.mock:MockAvatarBlock",
    "vision.mock": "blocks.vision.mock:MockVisionBlock",
    # 真实 Adapter（阶段 5+ 实装，这里先注册 entrypoint）
    "vad.silero": "blocks.vad.silero:SileroVadBlock",
    "stt.sensevoice": "blocks.stt.sensevoice:SenseVoiceSttBlock",
    "stt.openai-compatible": "blocks.stt.openai_compatible:OpenAISttBlock",
    "llm.openai-compatible": "blocks.llm.openai_compatible:OpenAILlmBlock",
    "llm.ollama": "blocks.llm.ollama:OllamaLlmBlock",
    "tts.openai-compatible": "blocks.tts.openai_compatible:OpenAITtsBlock",
    "tts.qwen3": "blocks.tts.qwen3:Qwen3TtsBlock",
    "tts.voxcpm2": "blocks.tts.voxcpm2:VoxCpm2TtsBlock",
    "avatar.static": "blocks.avatar.static:StaticAvatarBlock",
    "avatar.musetalk": "blocks.avatar.musetalk:MuseTalkAvatarBlock",
    "avatar.flashhead": "blocks.avatar.flashhead:FlashHeadAvatarBlock",
    "vision.openai-compatible": "blocks.vision.openai_compatible:OpenAIVisionBlock",
}


def register_block(block_id: str, entrypoint: str) -> None:
    """第三方注册新 Block。"""
    BLOCK_REGISTRY[block_id] = entrypoint


class Orchestrator:
    """主编排器。

    生命周期：
        orch = Orchestrator(config)
        await orch.setup()             # 装配 Block + 起 EventBus
        session = await orch.start_session(persona_id=...)
        # 接收浏览器事件：await orch.ingest_audio(session, pcm)
        await orch.shutdown()
    """

    def __init__(
        self,
        config: OrchestratorConfig,
        *,
        event_sink: Callable[[Event], Awaitable[None]] | None = None,
    ) -> None:
        """
        Args:
            config: Orchestrator 配置。
            event_sink: 可选——所有 emit 的事件也会传给 sink（如 Gateway 转发到浏览器、
                        Recorder 落盘）。如果为 None，事件只在内部 EventBus 流通。
        """
        self.config = config
        self.event_sink = event_sink
        self.event_bus = EventBus(default_queue_size=512)
        self.sessions = SessionManager()

        # 装配的 Block 实例（category -> Block）
        self.blocks: dict[str, Block] = {}
        # 失败/降级记录
        self.degraded_blocks: dict[str, str] = {}  # category -> fallback block_id
        # Persona 上下文（session_id -> dict），切换 Persona 时更新
        self._persona_contexts: dict[str, dict[str, Any]] = {}
        # 内部任务（订阅消费者等）
        self._tasks: list[asyncio.Task[None]] = []
        self._setup_done = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """装配 Block 并连事件订阅。"""
        async with self._lock:
            if self._setup_done:
                return

            # 装配各 Block
            for category, block_ref in self.config.blocks.items():
                await self._setup_block(category, block_ref.id, block_ref.config, block_ref)

            # 装配内部事件订阅（连主链路）
            await self._wire_event_bus()

            self._setup_done = True
            logger.info(
                "Orchestrator setup complete: blocks=%s degraded=%s",
                list(self.blocks.keys()),
                list(self.degraded_blocks.keys()),
            )

    async def shutdown(self) -> None:
        """关闭所有 Block 和 EventBus。

        顺序很重要：先关 sessions（会 emit closed 事件）→ 再关 EventBus。
        否则 session.close() 往已关闭的 bus publish 会抛。
        """
        async with self._lock:
            # 1. 先关 sessions（emit session.closed）
            await self.sessions.close_all()

            # 2. 关 Block
            for block in self.blocks.values():
                try:
                    await block.shutdown()
                except Exception:
                    logger.exception("block shutdown error: %s", block.manifest().block_id)

            # 3. 取消内部任务
            for task in self._tasks:
                task.cancel()
            for task in self._tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self._tasks.clear()

            # 4. 最后关 EventBus
            await self.event_bus.close()
            self._setup_done = False

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    async def start_session(
        self,
        *,
        persona_id: str | None = None,
        workspace_root: str = ".",
    ) -> Session:
        """开始一个新会话。"""
        session = self.sessions.create_session(
            profile_id=self.config.profile_id,
            persona_id=persona_id,
            workspace_root=workspace_root,
        )
        session.set_emit_fn(self._on_event)
        await session.start()
        return session

    async def end_session(self, session: Session, reason: str = "normal") -> None:
        """结束会话。"""
        await session.close(reason)
        self.sessions.remove(session.session_id)

    # ------------------------------------------------------------------
    # Persona 切换
    # ------------------------------------------------------------------

    async def switch_persona(
        self,
        session: Session,
        persona: Any,
    ) -> None:
        """切换 Persona——同步更新 LLM instructions / TTS voice / Avatar asset / Memory namespace。

        persona 是鸭子类型，需有：id / prompt / voice_ref_audio / avatar_portrait /
        voice_block / avatar_block / memory_namespace 字段（见 blocks.persona.PersonaPackage）。

        切换是原子的：先更新所有上下文，再 emit persona.changed。
        如果某项缺失（如 avatar_portrait 为 None），保持原值。
        """
        from avatarloom_protocol import PERSONA_CHANGED

        # 更新 Session 元数据
        old_persona_id = session.persona_id
        session.persona_id = persona.id

        # 更新各 Block 的运行时上下文（v0.1 通过 persona 上下文传递）
        # LLM：instructions
        # TTS：voice ref
        # Avatar：portrait
        # Memory：namespace
        # 这些通过 BlockContext 传给 process()——orchestrator._make_block_handler 重建 ctx 时会读取
        # 这里记录到 session 级别供后续 process() 用
        self._persona_contexts[session.session_id] = {
            "persona_id": persona.id,
            "instructions": persona.prompt,
            "voice_ref": getattr(persona, "voice_ref_audio", None),
            "avatar_ref": getattr(persona, "avatar_portrait", None),
            "memory_namespace": getattr(persona, "memory_namespace", None),
        }

        await session._emit_event(  # type: ignore[attr-defined]
            Event(
                type=PERSONA_CHANGED,
                session_id=session.session_id,
                source="orchestrator",
                run_id=session.current_run_id,
                payload={
                    "persona_id": persona.id,
                    "llm_instructions_changed": True,
                    "tts_voice_changed": bool(getattr(persona, "voice_ref_audio", None)),
                    "avatar_asset_changed": bool(getattr(persona, "avatar_portrait", None)),
                    "memory_namespace": getattr(persona, "memory_namespace", None),
                },
            )
        )
        logger.info(
            "persona switched: %s -> %s (session %s)",
            old_persona_id,
            persona.id,
            session.session_id[:12],
        )

    # ------------------------------------------------------------------
    # 音频入口（浏览器上行）
    # ------------------------------------------------------------------

    async def ingest_audio(self, session: Session, pcm_b64: str, samples: int) -> None:
        """接收浏览器上行的 PCM16 音频 chunk。

        会发布 audio.appended 事件，触发 VAD→STT 链路。
        """
        event = Event(
            type=AUDIO_APPENDED,
            session_id=session.session_id,
            source="transport.ws",
            run_id=session.current_run_id,
            sequence=session.next_sequence(),
            payload={
                "pcm_b64": pcm_b64,
                "sample_rate": 16000,
                "channels": 1,
                "samples": samples,
            },
        )
        await self._on_event(event)

    async def handle_user_speech_started(self, session: Session) -> None:
        """VAD 检测到用户开始说话——可能触发打断。

        如果当前在 SPEAKING/THINKING，进入 INTERRUPTING，取消 LLM/TTS。
        """
        if not self.config.allow_interruption:
            return
        # 触发 speech_started——状态机自动决定是否进入 INTERRUPTING
        await session.try_trigger("speech_started")

        if session.state == State.INTERRUPTING:
            await self._do_interrupt(session)

    async def handle_user_speech_ended(self, session: Session) -> None:
        """VAD 检测到用户说完。"""
        await session.try_trigger("speech_ended")

    # ------------------------------------------------------------------
    # 内部：Block 装配
    # ------------------------------------------------------------------

    async def _setup_block(
        self,
        category: str,
        block_id: str,
        config: dict[str, Any],
        block_ref: Any,
    ) -> None:
        """装配单个 Block。失败时按 fallback 降级或 optional 跳过。"""
        entrypoint = BLOCK_REGISTRY.get(block_id)
        if entrypoint is None:
            # 与下方 setup 失败处理保持一致：fallback 降级 / optional 跳过 / 否则报错
            if block_ref.fallback:
                logger.warning(
                    "block %s not in registry, degrading -> %s",
                    block_id,
                    block_ref.fallback,
                )
                await self._setup_block(category, block_ref.fallback, config, block_ref)
                self.degraded_blocks[category] = block_ref.fallback
                return
            if block_ref.optional:
                logger.info("optional block %s not in registry, continuing", block_id)
                return
            raise BlockSetupError(
                block_id=block_id,
                message=(
                    f"block {block_id!r} not in BLOCK_REGISTRY. "
                    "检查 profile 中是否写错了 id，或通过 register_block() 注册自定义 Block。"
                ),
            )

        try:
            from avatarloom_sdk import create_block

            block = create_block(entrypoint)
        except BlockSetupError as e:
            logger.warning("block %s setup import failed: %s", block_id, e)
            if block_ref.fallback:
                await self._setup_block(category, block_ref.fallback, config, block_ref)
                self.degraded_blocks[category] = block_ref.fallback
                return
            if block_ref.optional:
                logger.info("optional block %s absent, continuing", block_id)
                return
            raise

        ctx = BlockContext(
            session_id="(global)",  # setup 阶段无 session
            run_id=None,
            workspace_root=".",
            config=config,
        )
        try:
            await block.setup(ctx)
            # 预热（warmup）可选
            await block.warmup()
            self.blocks[category] = block
            logger.info("block ready: %s -> %s", category, block_id)
        except Exception:
            logger.exception("block %s setup failed", block_id)
            if block_ref.fallback:
                logger.info("degrading %s -> %s", block_id, block_ref.fallback)
                await self._setup_block(category, block_ref.fallback, config, block_ref)
                self.degraded_blocks[category] = block_ref.fallback
                return
            if block_ref.optional:
                logger.info("optional block %s failed, continuing", block_id)
                return
            raise

    # ------------------------------------------------------------------
    # 内部：EventBus 连线
    # ------------------------------------------------------------------

    async def _wire_event_bus(self) -> None:
        """连事件订阅：把 Block 的 process() 挂到对应事件类型。"""
        # VAD 订阅 audio.appended
        if CATEGORY_VAD in self.blocks:
            vad = self.blocks[CATEGORY_VAD]
            await self.event_bus.subscribe(
                AUDIO_APPENDED,
                self._make_block_handler(vad),
                policy=BackpressurePolicy.DROP_OLDEST,
                queue_size=128,
            )

        # STT 订阅 speech.ended（语音端点）
        if CATEGORY_STT in self.blocks:
            stt = self.blocks[CATEGORY_STT]
            await self.event_bus.subscribe(
                "speech.*",
                self._make_block_handler(stt),
            )

        # LLM 订阅 transcript.completed
        if CATEGORY_LLM in self.blocks:
            llm = self.blocks[CATEGORY_LLM]
            await self.event_bus.subscribe(
                TRANSCRIPT_COMPLETED,
                self._make_block_handler(llm),
            )

        # TTS 订阅 llm.text.delta/done
        if CATEGORY_TTS in self.blocks:
            tts = self.blocks[CATEGORY_TTS]
            await self.event_bus.subscribe(
                "llm.text.*",
                self._make_block_handler(tts),
            )

        # Avatar 订阅 tts.audio.*（双写：TTS 同时给浏览器和 Avatar）
        if CATEGORY_AVATAR in self.blocks:
            avatar = self.blocks[CATEGORY_AVATAR]
            await self.event_bus.subscribe(
                "tts.audio.*",
                self._make_block_handler(avatar),
            )

        # Session 状态机订阅关键事件——驱动 trigger
        await self.event_bus.subscribe(
            SPEECH_DETECTED,
            self._on_speech_detected,
        )
        await self.event_bus.subscribe(
            SPEECH_ENDED,
            self._on_speech_ended,
        )
        await self.event_bus.subscribe(
            TRANSCRIPT_COMPLETED,
            self._on_transcript_completed,
        )
        await self.event_bus.subscribe(
            LLM_TEXT_DELTA,
            self._on_llm_text_delta,
        )
        await self.event_bus.subscribe(
            TTS_AUDIO_COMPLETED,
            self._on_tts_completed,
        )

    def _make_block_handler(self, block: Block) -> Callable[[Event], Awaitable[None]]:
        """把 Block 包装成 EventBus handler。

        每次调用重建 ctx（带正确 session_id/run_id）。
        """

        async def handler(event: Event) -> None:
            ctx = BlockContext(
                session_id=event.session_id,
                run_id=event.run_id,
                workspace_root=".",
                _emit_fn=self._on_event,
            )
            try:
                await block.process(ctx, event)
            except asyncio.CancelledError:
                raise
            except BlockError as e:
                if e.degraded:
                    logger.warning("block %s degraded: %s", block.manifest().block_id, e)
                else:
                    logger.exception("block %s error", block.manifest().block_id)
            except Exception:
                logger.exception("unhandled error in block %s", block.manifest().block_id)

        return handler

    # ------------------------------------------------------------------
    # 内部：事件出口（emit）
    # ------------------------------------------------------------------

    async def _on_event(self, event: Event) -> None:
        """所有事件的中枢：
        1. 发布到 EventBus（驱动后续 Block）
        2. 转发给 sink（Gateway→浏览器 / Recorder 落盘）

        shutdown 过程中 bus 可能已关闭——容错不抛。
        """
        try:
            await self.event_bus.publish(event)
        except RuntimeError:
            # bus 已关闭（shutdown 中），忽略
            pass
        if self.event_sink is not None:
            try:
                await self.event_sink(event)
            except Exception:
                logger.exception("event_sink error")

    # ------------------------------------------------------------------
    # 状态机驱动器
    # ------------------------------------------------------------------

    async def _on_speech_detected(self, event: Event) -> None:
        session = self.sessions.get(event.session_id)
        if session is None:
            return
        await self.handle_user_speech_started(session)

    async def _on_speech_ended(self, event: Event) -> None:
        session = self.sessions.get(event.session_id)
        if session is None:
            return
        await self.handle_user_speech_ended(session)

    async def _on_transcript_completed(self, event: Event) -> None:
        session = self.sessions.get(event.session_id)
        if session is None:
            return
        text = event.payload.get("text", "")
        if not text.strip():
            await session.try_trigger("transcript_empty")
            return
        # 开始新一轮 Run
        await session.start_new_run()
        await session.trigger("transcript_ready")

    async def _on_llm_text_delta(self, event: Event) -> None:
        session = self.sessions.get(event.session_id)
        if session is None:
            return
        # 第一个 delta 触发 THINKING -> SPEAKING
        if event.payload.get("text"):
            await session.try_trigger("llm_first_token")

    async def _on_tts_completed(self, event: Event) -> None:
        session = self.sessions.get(event.session_id)
        if session is None:
            return
        await session.try_trigger("response_done")

    # ------------------------------------------------------------------
    # 打断处理
    # ------------------------------------------------------------------

    async def _do_interrupt(self, session: Session) -> None:
        """执行打断：
        1. 重置所有 Block（清缓冲）
        2. 等用户是否继续说话决定转 LISTENING 或 IDLE
        """
        for block in self.blocks.values():
            try:
                await block.reset(session.session_id)
            except Exception:
                logger.exception("block reset error during interrupt")
        # 这里简化：直接转 IDLE（用户已停）。
        # 真实场景：VAD 检测用户仍在说话 → interrupt_done_speaking -> LISTENING
        await session.try_trigger("interrupt_done_silent")
