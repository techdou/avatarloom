"""Persona 加载器和 StaticAvatar 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from avatarloom_protocol import TTS_AUDIO_DELTA, Event
from avatarloom_sdk import BlockContext

from blocks.avatar.static import StaticAvatarBlock
from blocks.persona import PersonaError, load_persona

# ---------------------------------------------------------------------------
# Persona 加载
# ---------------------------------------------------------------------------


class TestPersonaLoader:
    def test_load_demo_persona(self) -> None:
        persona = load_persona("personas/demo-assistant")
        assert persona.id == "demo-assistant"
        assert persona.name == "Demo Assistant"
        assert "演示数字人" in persona.prompt
        assert persona.voice_block == "tts.mock"
        assert persona.avatar_block == "avatar.static"
        assert persona.memory_namespace == "demo-assistant"

    def test_missing_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PersonaError, match="not found"):
            load_persona(tmp_path / "nonexistent")

    def test_missing_yaml_raises(self, tmp_path: Path) -> None:
        (tmp_path / "persona.md").write_text("prompt", encoding="utf-8")
        with pytest.raises(PersonaError, match=r"persona.yaml not found"):
            load_persona(tmp_path)

    def test_missing_md_raises(self, tmp_path: Path) -> None:
        (tmp_path / "persona.yaml").write_text(
            "metadata:\n  id: test\n  name: Test\n",
            encoding="utf-8",
        )
        with pytest.raises(PersonaError, match=r"persona.md not found"):
            load_persona(tmp_path)

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        (tmp_path / "persona.yaml").write_text(":\n  - invalid: yaml: [", encoding="utf-8")
        (tmp_path / "persona.md").write_text("x", encoding="utf-8")
        with pytest.raises(PersonaError, match=r"invalid persona.yaml"):
            load_persona(tmp_path)

    def test_default_id_from_dirname(self, tmp_path: Path) -> None:
        (tmp_path / "persona.yaml").write_text("metadata:\n  name: No ID\n", encoding="utf-8")
        (tmp_path / "persona.md").write_text("prompt", encoding="utf-8")
        persona = load_persona(tmp_path)
        # 没声明 id，用目录名
        assert persona.id == tmp_path.name


# ---------------------------------------------------------------------------
# StaticAvatar
# ---------------------------------------------------------------------------


class TestStaticAvatar:
    async def test_no_portrait_uses_placeholder(self) -> None:
        block = StaticAvatarBlock()
        ctx = BlockContext(session_id="s1", run_id="r1", workspace_root=".")
        ctx.config = {}
        await block.setup(ctx)
        assert block._portrait_b64  # 有占位
        assert block.is_ready

    async def test_emits_speech_frame_on_audio_delta(self) -> None:
        block = StaticAvatarBlock()
        ctx = BlockContext(session_id="s1", run_id="r1", workspace_root=".")
        ctx.config = {}
        await block.setup(ctx)

        out: list[Event] = []

        async def cap(e: Event) -> None:
            out.append(e)

        ctx._emit_fn = cap  # type: ignore[attr-defined]
        ctx._logger = None  # type: ignore[attr-defined]

        event = Event(
            type=TTS_AUDIO_DELTA,
            session_id="s1",
            source="tts",
            payload={"pcm_b64": "AAAA", "samples": 100},
        )
        await block.process(ctx, event)
        assert len(out) == 1
        assert out[0].type == "avatar.speech_frame"
        assert out[0].payload["is_speech"] is True

    async def test_emits_idle_frame_on_completed(self) -> None:
        from avatarloom_protocol import TTS_AUDIO_COMPLETED

        block = StaticAvatarBlock()
        ctx = BlockContext(session_id="s1", run_id="r1", workspace_root=".")
        ctx.config = {}
        await block.setup(ctx)

        out: list[Event] = []

        async def cap(e: Event) -> None:
            out.append(e)

        ctx._emit_fn = cap  # type: ignore[attr-defined]
        ctx._logger = None  # type: ignore[attr-defined]

        event = Event(type=TTS_AUDIO_COMPLETED, session_id="s1", source="tts", payload={})
        await block.process(ctx, event)
        assert out[0].type == "avatar.idle_frame"
        assert out[0].payload["is_speech"] is False

    async def test_loads_portrait_from_file(self, tmp_path: Path) -> None:
        # 造假 portrait
        portrait = tmp_path / "face.jpg"
        portrait.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-data")
        block = StaticAvatarBlock()
        ctx = BlockContext(session_id="s1", run_id="r1", workspace_root=".")
        ctx.config = {"portrait": str(portrait)}
        await block.setup(ctx)
        import base64

        decoded = base64.b64decode(block._portrait_b64)
        assert b"fake-jpeg-data" in decoded


# ---------------------------------------------------------------------------
# Persona 切换（Orchestrator 集成）
# ---------------------------------------------------------------------------


class TestPersonaSwitch:
    async def test_switch_persona_emits_event(self) -> None:
        from runtime.orchestrator import Orchestrator
        from runtime.orchestrator.config import BlockRef, OrchestratorConfig

        emitted: list = []

        async def sink(e) -> None:
            emitted.append(e)

        config = OrchestratorConfig(
            blocks={
                "llm": BlockRef(id="llm.mock", deployment="mock", config={"chunk_delay_ms": 0})
            },
        )
        orch = Orchestrator(config, event_sink=sink)
        await orch.setup()
        session = await orch.start_session()

        # 构造一个 mock persona
        class MockPersona:
            id = "persona-2"
            prompt = "你是另一个助手"
            voice_ref_audio = None
            avatar_portrait = None
            memory_namespace = "persona-2"

        await orch.switch_persona(session, MockPersona())  # type: ignore[arg-type]

        assert session.persona_id == "persona-2"
        # 应 emit persona.changed
        types = [getattr(e, "type", None) for e in emitted]
        assert "persona.changed" in types

        await orch.shutdown()

    async def test_persona_context_stored(self) -> None:
        from runtime.orchestrator import Orchestrator
        from runtime.orchestrator.config import BlockRef, OrchestratorConfig

        async def sink(e) -> None:
            pass

        config = OrchestratorConfig(
            blocks={"llm": BlockRef(id="llm.mock", deployment="mock")},
        )
        orch = Orchestrator(config, event_sink=sink)
        await orch.setup()
        session = await orch.start_session()

        class MockPersona:
            id = "p1"
            prompt = "test prompt"
            voice_ref_audio = "/path/to/voice.wav"
            avatar_portrait = "/path/to/face.png"
            memory_namespace = "p1"

        await orch.switch_persona(session, MockPersona())  # type: ignore[arg-type]
        ctx = orch._persona_contexts[session.session_id]
        assert ctx["instructions"] == "test prompt"
        assert ctx["voice_ref"] == "/path/to/voice.wav"
        assert ctx["avatar_ref"] == "/path/to/face.png"

        await orch.shutdown()
