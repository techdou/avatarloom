"""Run Recorder 和 Artifact Writer 测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from avatarloom_protocol import (
    AVATAR_DEGRADED,
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    SESSION_STATE_CHANGED,
    TRANSCRIPT_COMPLETED,
    Event,
)

from runtime.recorder import ArtifactWriter, RunRecorder


@pytest.fixture
def runs_root(tmp_path: Path) -> Path:
    return tmp_path / "runs"


@pytest.fixture
def artifacts_root(tmp_path: Path) -> Path:
    return tmp_path / "artifacts"


class TestRunRecorder:
    async def test_start_and_finalize_creates_files(self, runs_root: Path) -> None:
        recorder = RunRecorder(root=runs_root)
        await recorder.start_run(
            "run_test1",
            "ses_1",
            "mock",
            runtime_config={"key": "value"},
            block_versions={"vad.mock": "0.1.0"},
        )
        # record 一些事件
        await recorder.record(
            Event(
                type=TRANSCRIPT_COMPLETED,
                session_id="ses_1",
                source="stt.mock",
                run_id="run_test1",
                timestamp=1000,
                payload={"text": "你好"},
            )
        )
        await recorder.record(
            Event(
                type=LLM_TEXT_DELTA,
                session_id="ses_1",
                source="llm.mock",
                run_id="run_test1",
                timestamp=1100,
                payload={"text": "你好", "is_sentence_end": False},
            )
        )
        await recorder.record(
            Event(
                type=LLM_TEXT_DONE,
                session_id="ses_1",
                source="llm.mock",
                run_id="run_test1",
                timestamp=1200,
                payload={"full_text": "你好，我是助手"},
            )
        )
        await asyncio.sleep(0.01)
        await recorder.finalize_run("run_test1", status="completed")

        run_dir = runs_root / "run_test1"
        assert (run_dir / "manifest.json").exists()
        assert (run_dir / "events.jsonl").exists()
        assert (run_dir / "metrics.json").exists()
        assert (run_dir / "transcript.json").exists()
        assert (run_dir / "runtime-config.json").exists()

    async def test_metrics_first_text_ms(self, runs_root: Path) -> None:
        recorder = RunRecorder(root=runs_root)
        await recorder.start_run("run_x", "ses_1", "mock")
        # started_at 约 now，第一个 LLM delta 在 +500ms
        # 但 event.timestamp 是事件自带的绝对时间——需要稍大于 started_at

        await asyncio.sleep(0.05)
        state = recorder._active["run_x"]
        started = state.metrics.started_at_ms

        await recorder.record(
            Event(
                type=LLM_TEXT_DELTA,
                session_id="ses_1",
                source="llm",
                run_id="run_x",
                timestamp=started + 500,
                payload={"text": "你好"},
            )
        )
        await recorder.finalize_run("run_x")
        metrics = recorder.load_metrics("run_x")
        assert metrics is not None
        assert metrics["first_text_ms"] is not None
        assert metrics["first_text_ms"] >= 0

    async def test_events_jsonl_one_per_line(self, runs_root: Path) -> None:
        recorder = RunRecorder(root=runs_root)
        await recorder.start_run("run_y", "ses_1", "mock")
        for i in range(5):
            await recorder.record(
                Event(
                    type="test.event",
                    session_id="ses_1",
                    source="x",
                    run_id="run_y",
                    timestamp=i * 1000,
                    payload={"i": i},
                )
            )
        await recorder.finalize_run("run_y")

        events = recorder.load_events("run_y")
        assert len(events) == 5
        assert events[0]["payload"]["i"] == 0
        assert events[4]["payload"]["i"] == 4

    async def test_concurrent_record_no_line_interleaving(self, runs_root: Path) -> None:
        """并发 record() 回归：JSONL 每行必须是完整可解析的 JSON，且事件不丢失。

        历史缺陷：write 移出锁后用 to_thread 并发写同一文件句柄导致行内容交错；
        本测试在回退前的代码上必然失败，锁住"锁内串行 + 线程池 I/O"的修复。
        """
        recorder = RunRecorder(root=runs_root)
        await recorder.start_run("run_conc", "ses_1", "mock")
        n = 50
        await asyncio.gather(
            *[
                recorder.record(
                    Event(
                        type="test.event",
                        session_id="ses_1",
                        source="x",
                        run_id="run_conc",
                        timestamp=i,
                        payload={"i": i, "pad": "x" * 128},
                    )
                )
                for i in range(n)
            ]
        )
        await recorder.finalize_run("run_conc")

        raw = (runs_root / "run_conc" / "events.jsonl").read_text(encoding="utf-8")
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        assert len(lines) == n, f"expected {n} lines, got {len(lines)}"
        parsed = [json.loads(ln) for ln in lines]  # 任一行解析失败即证明行交错
        assert sorted(e["payload"]["i"] for e in parsed) == list(range(n))

    async def test_transcript_records_user_and_assistant(self, runs_root: Path) -> None:
        recorder = RunRecorder(root=runs_root)
        await recorder.start_run("run_t", "ses_1", "mock")
        await recorder.record(
            Event(
                type=TRANSCRIPT_COMPLETED,
                session_id="ses_1",
                source="stt",
                run_id="run_t",
                timestamp=0,
                payload={"text": "你是谁"},
            )
        )
        await recorder.record(
            Event(
                type=LLM_TEXT_DONE,
                session_id="ses_1",
                source="llm",
                run_id="run_t",
                timestamp=100,
                payload={"full_text": "我是 AvatarLoom 助手"},
            )
        )
        await recorder.finalize_run("run_t")
        transcript = recorder.load_transcript("run_t")
        assert transcript["user"] == "你是谁"
        assert transcript["assistant"] == "我是 AvatarLoom 助手"
        assert len(transcript["rounds"]) == 2

    async def test_interruption_counted(self, runs_root: Path) -> None:
        recorder = RunRecorder(root=runs_root)
        await recorder.start_run("run_i", "ses_1", "mock")
        await recorder.record(
            Event(
                type=SESSION_STATE_CHANGED,
                session_id="ses_1",
                source="sm",
                run_id="run_i",
                timestamp=0,
                payload={"from": "speaking", "to": "interrupting"},
            )
        )
        await recorder.finalize_run("run_i", status="interrupted")
        metrics = recorder.load_metrics("run_i")
        assert metrics["interruptions"] == 1
        assert metrics["cancelled"] is True

    async def test_degradation_counted(self, runs_root: Path) -> None:
        recorder = RunRecorder(root=runs_root)
        await recorder.start_run("run_d", "ses_1", "mock")
        await recorder.record(
            Event(
                type=AVATAR_DEGRADED,
                session_id="ses_1",
                source="avatar",
                run_id="run_d",
                timestamp=0,
                payload={"from_block": "avatar.musetalk", "to_block": "avatar.static"},
            )
        )
        await recorder.finalize_run("run_d")
        metrics = recorder.load_metrics("run_d")
        assert metrics["degradations"] == 1
        assert metrics["degraded_blocks"]["avatar.musetalk"] == "avatar.static"

    async def test_record_without_active_run_is_noop(self, runs_root: Path) -> None:
        recorder = RunRecorder(root=runs_root)
        # run_id 不在 active 中——不抛
        await recorder.record(
            Event(
                type="x",
                session_id="s",
                source="b",
                run_id="run_unknown",
            )
        )

    async def test_list_runs(self, runs_root: Path) -> None:
        recorder = RunRecorder(root=runs_root)
        await recorder.start_run("run_a", "ses_1", "mock")
        await recorder.finalize_run("run_a")
        await recorder.start_run("run_b", "ses_1", "mock")
        await recorder.finalize_run("run_b")
        runs = recorder.list_runs()
        assert "run_a" in runs
        assert "run_b" in runs


class TestArtifactWriter:
    def test_write_bytes(self, artifacts_root: Path) -> None:
        writer = ArtifactWriter(root=artifacts_root)
        record = writer.write_bytes(
            "run_1",
            "audio",
            "output.wav",
            b"RIFF\x00\x00\x00\x00",
            mime_type="audio/wav",
            metadata={"duration_ms": 1000},
        )
        assert record.artifact_id.startswith("art_")
        assert record.kind == "audio"
        assert "run_1" in record.path
        # 文件实际写入
        assert (artifacts_root / record.path).exists()
        assert (artifacts_root / record.path).read_bytes() == b"RIFF\x00\x00\x00\x00"

    def test_write_text(self, artifacts_root: Path) -> None:
        writer = ArtifactWriter(root=artifacts_root)
        record = writer.write_text("run_1", "text", "transcript.txt", "你好")
        assert record.mime_type == "text/plain; charset=utf-8"
        assert (artifacts_root / record.path).read_text(encoding="utf-8") == "你好"

    def test_write_json(self, artifacts_root: Path) -> None:
        writer = ArtifactWriter(root=artifacts_root)
        obj = {"a": 1, "b": [1, 2, 3], "中文": "测试"}
        record = writer.write_json("run_1", "data.json", obj)
        loaded = json.loads((artifacts_root / record.path).read_text(encoding="utf-8"))
        assert loaded == obj

    def test_list_artifacts(self, artifacts_root: Path) -> None:
        writer = ArtifactWriter(root=artifacts_root)
        writer.write_text("run_1", "text", "a.txt", "a")
        writer.write_text("run_1", "text", "b.txt", "b")
        writer.write_text("run_2", "text", "c.txt", "c")
        run1 = writer.list_artifacts("run_1")
        run2 = writer.list_artifacts("run_2")
        assert len(run1) == 2
        assert len(run2) == 1

    def test_path_traversal_blocked(self, artifacts_root: Path) -> None:
        writer = ArtifactWriter(root=artifacts_root)
        with pytest.raises(ValueError, match=r"\.\."):
            writer.resolve_path("../etc/passwd")

    def test_resolve_path_normal(self, artifacts_root: Path) -> None:
        writer = ArtifactWriter(root=artifacts_root)
        p = writer.resolve_path("audio/run_1/x.wav")
        assert p == artifacts_root / "audio" / "run_1" / "x.wav"
