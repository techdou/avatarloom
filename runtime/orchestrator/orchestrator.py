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
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from avatarloom_protocol import (
    AUDIO_APPENDED,
    LLM_REQUEST,
    LLM_TEXT_DELTA,
    SPEECH_DETECTED,
    SPEECH_ENDED,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_COMPLETED,
    VISION_REQUEST,
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

# 视觉触发词：用户说出这些词 → 下行 vision.request 让浏览器截帧分析
_VISION_TRIGGER_RE = re.compile(r"看看|评价|describe|looks?\s+like", re.IGNORECASE)

# 视觉上下文有效期（秒）：超过后不再注入 LLM
_VISION_CONTEXT_TTL_S = 30.0
# Vision 手动帧最小调用间隔（AL-P1-011 节流）——无同轮等待的帧限频
_VISION_MIN_INTERVAL_S = 2.0


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
        # 各 Block 的运行期配置（category -> config），process 阶段注入 BlockContext
        self._block_configs: dict[str, dict[str, Any]] = {}
        # 失败/降级记录
        self.degraded_blocks: dict[str, str] = {}  # category -> fallback block_id
        # Persona 上下文（session_id -> dict），切换 Persona 时更新
        self._persona_contexts: dict[str, dict[str, Any]] = {}
        # 视觉感知上下文：session_id -> {"description", "request_id", "ts"}，
        # 单次消费 + TTL（_VISION_CONTEXT_TTL_S），供 LLM 下一轮回复注入
        self._vision_contexts: dict[str, dict[str, Any]] = {}
        # 同轮 Vision 等待：session_id -> (request_id, Future)。
        # 触发词命中后挂起，ingest_vision_frame/超时/打断时 resolve。
        self._vision_pending: dict[str, tuple[str, asyncio.Future[None]]] = {}
        # Vision 调用并发锁与节流（AL-P1-011）：同 session 同时仅 1 个多模态调用；
        # 无同轮等待的手动帧受最小间隔限制——任意频率帧都会触发远程 API（费用风险）
        self._vision_locks: dict[str, asyncio.Lock] = {}
        self._vision_last_call: dict[str, float] = {}
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
        """开始一个新会话。

        传 persona_id 时自动加载 persona 并填充 _persona_contexts——
        否则 LLM 拿不到 persona_instructions（强约束失效）、TTS 拿不到
        voice_ref（音色克隆失效）。修复：gateway session.start 只调本方法
        不调 switch_persona 导致上下文恒空的 bug。
        """
        session = self.sessions.create_session(
            profile_id=self.config.profile_id,
            persona_id=persona_id,
            workspace_root=workspace_root,
        )
        session.set_emit_fn(self._on_event)
        await session.start()

        if persona_id:
            try:
                from blocks.persona.loader import load_persona

                persona = load_persona(
                    Path(workspace_root) / "personas" / persona_id,
                    workspace_root=workspace_root,
                )
                await self._apply_persona_context(session, persona)
            except Exception as e:
                logger.warning("persona %s 加载失败（继续用 profile 默认）: %s", persona_id, e)

        return session

    async def end_session(self, session: Session, reason: str = "normal") -> None:
        """结束会话——同时清理 Persona/Vision 上下文和 pending Vision 等待。"""
        # 取消挂起的同轮 Vision 等待（等待方收到 CancelledError 后跳过 LLM）
        pending = self._vision_pending.pop(session.session_id, None)
        if pending is not None and not pending[1].done():
            pending[1].cancel()
        self._persona_contexts.pop(session.session_id, None)
        self._vision_contexts.pop(session.session_id, None)
        self._vision_locks.pop(session.session_id, None)
        self._vision_last_call.pop(session.session_id, None)
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

        await self._apply_persona_context(session, persona)

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

    async def _apply_persona_context(self, session: Session, persona: Any) -> None:
        """把 persona 上下文写入 _persona_contexts（LLM instructions / TTS voice / Avatar asset）。

        start_session 和 switch_persona 共用——缺此注入时 LLM 拿不到
        persona_instructions（强约束失效）、TTS 拿不到 voice_ref（克隆失效）。
        """
        self._persona_contexts[session.session_id] = {
            "persona_id": persona.id,
            "instructions": persona.prompt,
            "voice_ref": getattr(persona, "voice_ref_audio", None),
            "avatar_ref": getattr(persona, "avatar_portrait", None),
            "memory_namespace": getattr(persona, "memory_namespace", None),
        }

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

    async def ingest_vision_frame(self, session: Session, jpeg_b64: str) -> None:
        """接收浏览器摄像头截帧（0x02 上行），调用 vision block 多模态分析。

        结果存到 _vision_contexts（单次消费 + TTL，供 LLM 注入）；若本轮有
        挂起的同轮 Vision 等待（触发词命中），resolve 它让 LLM 立即继续。
        vision block 缺席时静默跳过（不阻断主链路）。
        """
        vision = self.blocks.get(CATEGORY_VISION)
        if vision is None:
            logger.info("vision block 未装配，跳过摄像头帧分析")
            self._resolve_vision_pending(session.session_id)
            return
        pending = self._vision_pending.get(session.session_id)
        # AL-P1-011 并发锁：同 session 已有 vision 调用进行中 → 丢弃重复帧。
        # 进行中的调用会 resolve pending（若有），新帧无需再调远程 API。
        lock = self._vision_locks.setdefault(session.session_id, asyncio.Lock())
        if lock.locked():
            logger.info(
                "vision 调用进行中，丢弃重复帧 (session %s)",
                session.session_id[:12],
            )
            return
        # AL-P1-011 节流：无同轮等待的手动帧受最小间隔限制（费用控制）。
        # 有 pending（触发词同轮）的帧必须服务——它是本轮回答的前提。
        if pending is None:
            last = self._vision_last_call.get(session.session_id, 0.0)
            gap = time.monotonic() - last
            if gap < _VISION_MIN_INTERVAL_S:
                logger.info(
                    "vision 帧节流丢弃（距上次 %.1fs < %.1fs, session %s）",
                    gap,
                    _VISION_MIN_INTERVAL_S,
                    session.session_id[:12],
                )
                return
        self._vision_last_call[session.session_id] = time.monotonic()
        request_id = pending[0] if pending else None
        ctx = BlockContext(
            session_id=session.session_id,
            run_id=session.current_run_id,
            workspace_root=".",
            config=self._block_configs.get(CATEGORY_VISION, {}),
            _emit_fn=self._on_event,
        )
        async with lock:
            try:
                result = await vision.describe_frame(
                    ctx,
                    jpeg_b64,
                    prompt=(
                        "描述这张图片里的内容，包括人物外貌特征、穿着、表情、"
                        "以及周围环境。用中文，2-3 句话。"
                    ),
                    request_id=request_id,
                )
                description = result.payload.get("description", "")
                if description and "视觉感知失败" not in description:
                    self._vision_contexts[session.session_id] = {
                        "description": description,
                        "request_id": request_id,
                        "ts": time.monotonic(),
                    }
                    logger.info(
                        "vision 分析完成 (session %s, req %s): %.60s",
                        session.session_id[:12],
                        (request_id or "-")[:12],
                        description,
                    )
            except Exception as e:
                logger.warning("vision describe_frame 失败: %s", e)
            finally:
                # 成功/失败都唤醒同轮等待——失败走降级回答，不让 LLM 干等超时
                self._resolve_vision_pending(session.session_id)

    async def handle_vision_frame_error(self, session: Session, reason: str) -> None:
        """浏览器截帧失败（摄像头拒绝/不可用）——立即降级，不等超时。"""
        logger.info(
            "vision 截帧失败 (session %s): %s——降级为无视觉回答",
            session.session_id[:12],
            reason,
        )
        self._resolve_vision_pending(session.session_id)

    def _resolve_vision_pending(self, session_id: str) -> None:
        """唤醒 session 上挂起的同轮 Vision 等待（若有）。"""
        pending = self._vision_pending.pop(session_id, None)
        if pending is not None and not pending[1].done():
            pending[1].set_result(None)

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
        _visited: frozenset[str] = frozenset(),
    ) -> None:
        """装配单个 Block。失败时按 fallback 降级或 optional 跳过。

        _visited 防 fallback 链自指/成环：flashhead→musetalk 失败后，
        musetalk 再失败会用同一 block_ref.fallback 无限递归（真实发生过的隐患）。
        """
        if block_id in _visited:
            if block_ref.optional:
                logger.info("optional block %s fallback cycle, skipping", block_id)
                return
            raise BlockSetupError(
                block_id=block_id,
                message=(
                    f"fallback 链成环：{' -> '.join(sorted(_visited | {block_id}))}。"
                    "检查 profile 中 fallback 配置。"
                ),
            )
        visited = _visited | {block_id}
        entrypoint = BLOCK_REGISTRY.get(block_id)
        if entrypoint is None:
            # 与下方 setup 失败处理保持一致：fallback 降级 / optional 跳过 / 否则报错
            if block_ref.fallback:
                logger.warning(
                    "block %s not in registry, degrading -> %s",
                    block_id,
                    block_ref.fallback,
                )
                await self._setup_block(category, block_ref.fallback, config, block_ref, visited)
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
                await self._setup_block(category, block_ref.fallback, config, block_ref, visited)
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
            # 保存运行期配置——process 阶段注入 BlockContext（AL-P1-009：
            # 此前只在 setup 注入，LLM 运行期读 systemPrompt 恒为空）
            self._block_configs[category] = config
            logger.info("block ready: %s -> %s", category, block_id)
        except Exception:
            logger.exception("block %s setup failed", block_id)
            if block_ref.fallback:
                logger.info("degrading %s -> %s", block_id, block_ref.fallback)
                await self._setup_block(category, block_ref.fallback, config, block_ref, visited)
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
        # VAD 订阅 audio.appended（DROP_OLDEST 可接受：VAD 丢帧只影响检测粒度）
        if CATEGORY_VAD in self.blocks:
            vad = self.blocks[CATEGORY_VAD]
            await self.event_bus.subscribe(
                AUDIO_APPENDED,
                self._make_block_handler(vad, CATEGORY_VAD),
                policy=BackpressurePolicy.DROP_OLDEST,
                queue_size=128,
            )

        # STT 订阅 audio.appended（累积音频缓冲）+ speech.ended（触发转写）。
        # 真实 SenseVoice 需要 audio.appended 才能拿到 PCM——只订 speech.* 时
        # _audio_buffers 恒空，transcript 永不触发（mock 测试掩盖了此 bug）。
        # AL-P1-007：STT 累积 PCM，DROP_OLDEST 丢一条就剪一段语音——改 BLOCK
        # （背压沿 WS/TCP 自然回传，浏览器端音频缓冲承受，不丢音频）。
        if CATEGORY_STT in self.blocks:
            stt = self.blocks[CATEGORY_STT]
            await self.event_bus.subscribe(
                AUDIO_APPENDED,
                self._make_block_handler(stt, CATEGORY_STT),
                policy=BackpressurePolicy.BLOCK,
                queue_size=512,
            )
            await self.event_bus.subscribe(
                SPEECH_ENDED,
                self._make_block_handler(stt, CATEGORY_STT),
            )

        # LLM 订阅 llm.request（AL-P1-002：不再直接消费 transcript.completed——
        # Orchestrator 先做 Vision 同轮决策，vision.result/超时后才发 llm.request）
        if CATEGORY_LLM in self.blocks:
            llm = self.blocks[CATEGORY_LLM]
            await self.event_bus.subscribe(
                LLM_REQUEST,
                self._make_block_handler(llm, CATEGORY_LLM),
            )

        # TTS 订阅 llm.text.delta/done
        if CATEGORY_TTS in self.blocks:
            tts = self.blocks[CATEGORY_TTS]
            await self.event_bus.subscribe(
                "llm.text.*",
                self._make_block_handler(tts, CATEGORY_TTS),
            )

        # Avatar 订阅 tts.audio.*（双写：TTS 同时给浏览器和 Avatar）
        # 以及 speech.*（VAD 事件推导 idle_mode，对齐 VoxEMW avatar_state_transition）
        if CATEGORY_AVATAR in self.blocks:
            avatar = self.blocks[CATEGORY_AVATAR]
            await self.event_bus.subscribe(
                "tts.audio.*",
                self._make_block_handler(avatar, CATEGORY_AVATAR),
            )
            await self.event_bus.subscribe(
                "speech.*",
                self._make_block_handler(avatar, CATEGORY_AVATAR),
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

    def _make_block_handler(
        self, block: Block, category: str
    ) -> Callable[[Event], Awaitable[None]]:
        """把 Block 包装成 EventBus handler。

        每次调用重建 ctx（带正确 session_id/run_id/config/persona）。
        Vision 描述只注入 LLM（单次消费 + TTL），其他 category 不触碰。
        """

        async def handler(event: Event) -> None:
            persona_ctx = self._persona_contexts.get(event.session_id, {})
            # AL-P1-003：只有 LLM 消费视觉描述——其他 Block 经手会提前消耗
            vision_description = None
            if category == CATEGORY_LLM:
                vision_description = self._consume_vision_context(event.session_id)
            ctx = BlockContext(
                session_id=event.session_id,
                run_id=event.run_id,
                workspace_root=".",
                config=self._block_configs.get(category, {}),
                _emit_fn=self._on_event,
                persona_id=persona_ctx.get("persona_id"),
                persona_instructions=persona_ctx.get("instructions"),
                persona_voice_ref=persona_ctx.get("voice_ref"),
                persona_avatar_ref=persona_ctx.get("avatar_ref"),
                vision_description=vision_description,
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

    def _consume_vision_context(self, session_id: str) -> str | None:
        """取出 session 的视觉描述（单次消费 + TTL 过期清理）。"""
        entry = self._vision_contexts.pop(session_id, None)
        if entry is None:
            return None
        age = time.monotonic() - float(entry.get("ts", 0.0))
        if age > _VISION_CONTEXT_TTL_S:
            logger.info("vision context 已过期（%.1fs），丢弃", age)
            return None
        return str(entry.get("description") or "") or None

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
        """transcript 决策中枢（AL-P1-002 同轮编排）：

        1. 先建新 Run（AL-P1-005：下游 vision/llm/tts 都带正确 run_id）
        2. 命中触发词且有 vision block → 下行 vision.request 并等待
           vision.result（成功/失败/截帧报错都唤醒）或超时降级
        3. 发 llm.request 驱动 LLM 生成——LLM 不再直接消费 transcript
        """
        # 重发副本（re_emitted）防御：副本只应走 sink，若意外进 bus 直接丢弃，
        # 否则本 handler 会被副本再次触发——start_new_run → 重发 → 无限循环。
        if event.payload.get("re_emitted"):
            return
        session = self.sessions.get(event.session_id)
        if session is None:
            return
        text = event.payload.get("text", "")
        if not text.strip():
            await session.try_trigger("transcript_empty")
            return

        # 新一轮 Run——必须在发下游事件之前
        await session.start_new_run()
        # AL-P1-005：STT 发出的原始 transcript.completed 携带旧 run_id（或 None），
        # 到达 Recorder 时新 run 尚未建立而被丢弃——用新 run_id 重发一份，
        # 让 Recorder 落录本轮用户文本、前端事件流正确归属新 run。
        # 副本只经 sink（Gateway/Recorder/前端），不回灌 bus——
        # 否则本 handler 会被副本再次触发，无限创建 run（实测卡死）。
        # re_emitted 标记：handler 防御性丢弃 + 前端去重不重复渲染气泡。
        if self.event_sink is not None:
            try:
                await self.event_sink(
                    Event(
                        type=TRANSCRIPT_COMPLETED,
                        session_id=session.session_id,
                        source="orchestrator.run",
                        run_id=session.current_run_id,
                        payload={**event.payload, "re_emitted": True},
                    )
                )
            except Exception:
                logger.exception("event_sink error")
        # 状态机驱动用 try_trigger：transcript 在 thinking/speaking 期间到达
        # 属合法边缘（VAD 未捕获 speech_started），不能让状态缺口杀掉回答链路
        new_state = await session.try_trigger("transcript_ready")
        if new_state is None:
            logger.warning(
                "transcript_ready 在当前状态 %s 下非法，仍继续 LLM 链路（session %s）",
                session.state.value,
                session.session_id[:12],
            )

        # 触发词检测：命中 → 截帧分析，等同轮视觉结果再回答
        m = _VISION_TRIGGER_RE.search(text)
        if m and CATEGORY_VISION in self.blocks:
            proceed = await self._request_vision_and_wait(session, keyword=m.group(0))
            if not proceed:
                # 被打断/会话结束——跳过本轮 LLM
                return
        elif m:
            logger.info("命中视觉触发词但 vision block 未装配，直接回答")

        await self._on_event(
            Event(
                type=LLM_REQUEST,
                session_id=session.session_id,
                source="orchestrator",
                run_id=session.current_run_id,
                payload={
                    "text": text,
                    "language": event.payload.get("language", "zh"),
                    "transcript_event_id": event.id,
                },
            )
        )

    async def _request_vision_and_wait(self, session: Session, keyword: str) -> bool:
        """下行 vision.request 并挂起等待截帧分析。返回 True=继续 LLM。

        唤醒路径：ingest_vision_frame（成功/失败）/ handle_vision_frame_error /
        超时降级。打断或会话结束 → Future 被 cancel → 返回 False 跳过 LLM。
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        request_id = f"vreq_{uuid.uuid4().hex[:12]}"
        # 同 session 已有 pending（连说两次触发词）→ 取消旧的，以新请求为准
        old = self._vision_pending.pop(session.session_id, None)
        if old is not None and not old[1].done():
            old[1].cancel()
        self._vision_pending[session.session_id] = (request_id, fut)

        await self._on_event(
            Event(
                type=VISION_REQUEST,
                session_id=session.session_id,
                source="orchestrator.trigger",
                run_id=session.current_run_id,
                payload={"keyword": keyword, "request_id": request_id},
            )
        )

        timeout = float(self.config.vision_timeout_s)
        try:
            # shield：超时只放弃等待，不取消 fut——迟到的截帧仍可存上下文
            await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
            return True
        except TimeoutError:
            self._vision_pending.pop(session.session_id, None)
            logger.info(
                "vision 等待超时（%.1fs, session %s）——降级为无视觉回答",
                timeout,
                session.session_id[:12],
            )
            return True
        except asyncio.CancelledError:
            # 区分两种取消（Python 语义：吞掉 task.cancel() 又不 re-raise，
            # 任务会继续跑——asyncio.run/shutdown 的 gather 会因此永远等它）：
            # - fut 被 _do_interrupt/end_session 取消（任务本身未被 cancel）
            #   → 内部打断，跳过本轮 LLM，返回 False
            # - 消费者任务自身被 cancel（bus 关闭/loop teardown）
            #   → 必须 re-raise 让任务正常消亡
            task = asyncio.current_task()
            if fut.cancelled() and (task is None or task.cancelling() == 0):
                self._vision_pending.pop(session.session_id, None)
                logger.info(
                    "vision 等待被打断（session %s），跳过本轮 LLM",
                    session.session_id[:12],
                )
                return False
            raise

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
        1. 取消挂起的同轮 Vision 等待（跳过本轮 LLM）
        2. 重置所有 Block（清缓冲）
        3. 等用户是否继续说话决定转 LISTENING 或 IDLE
        """
        pending = self._vision_pending.pop(session.session_id, None)
        if pending is not None and not pending[1].done():
            pending[1].cancel()
        for block in self.blocks.values():
            try:
                await block.reset(session.session_id)
            except Exception:
                logger.exception("block reset error during interrupt")
        # 这里简化：直接转 IDLE（用户已停）。
        # 真实场景：VAD 检测用户仍在说话 → interrupt_done_speaking -> LISTENING
        await session.try_trigger("interrupt_done_silent")
