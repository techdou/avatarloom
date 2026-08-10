"""RunRecorder 实现。

订阅 Orchestrator 的 event_sink，每轮 Run 落盘一份完整记录。

用例：
    recorder = RunRecorder(root="./data/runs")
    await recorder.start_run(run_id, session_id, profile_id, ...)
    # Orchestrator emit 的事件全部传给 recorder.record(event)
    await recorder.finalize_run(run_id, status="completed")
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from avatarloom_protocol import (
    ARTIFACT_CREATED,
    AVATAR_DEGRADED,
    AVATAR_IDLE_FRAME,
    AVATAR_SPEECH_FRAME,
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    RESPONSE_DONE,
    RESPONSE_INTERRUPTED,
    SESSION_STATE_CHANGED,
    TRANSCRIPT_COMPLETED,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    Event,
)

# metrics.py 的 RunMetrics 已在 __init__ 导出，但 recorder 直接 import 路径更清晰
from runtime.recorder.metrics import RunMetrics

logger = logging.getLogger(__name__)


class RunRecorder:
    """记录单轮 Run 的所有事件和指标到文件系统。

    线程安全：单 Run 内的 record() 由 Orchestrator 串行调用（event_sink），
    但 finalize 可能异步——用锁保护文件写入。
    """

    def __init__(self, root: str | Path = "./data/runs") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # run_id -> 当前活跃记录状态
        self._active: dict[str, _RunState] = {}
        self._lock = asyncio.Lock()
        # flush 降频参数：高频音频事件下每秒 20-40 次 flush 浪费 syscalls。
        # write 留锁内（防并发交错），flush 改按时间窗口批量；finalize 强制 flush。
        self._flush_interval_s = 0.5

    async def start_run(
        self,
        run_id: str,
        session_id: str,
        profile_id: str,
        *,
        persona_id: str | None = None,
        runtime_config: dict[str, Any] | None = None,
        block_versions: dict[str, str] | None = None,
    ) -> None:
        """开始记录一轮 Run。"""
        async with self._lock:
            run_dir = self.root / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "input").mkdir(exist_ok=True)
            (run_dir / "output").mkdir(exist_ok=True)
            (run_dir / "snapshots").mkdir(exist_ok=True)

            now_ms = int(time.time() * 1000)
            state = _RunState(
                run_id=run_id,
                session_id=session_id,
                profile_id=profile_id,
                persona_id=persona_id,
                started_at_ms=now_ms,
                run_dir=run_dir,
                metrics=RunMetrics(
                    run_id=run_id,
                    session_id=session_id,
                    profile_id=profile_id,
                    persona_id=persona_id,
                    started_at_ms=now_ms,
                    block_versions=block_versions or {},
                ),
                events_file=open(  # noqa: SIM115, ASYNC230 - 跨方法持有，事件量小，阻塞可接受
                    run_dir / "events.jsonl", "a", encoding="utf-8"
                ),
                runtime_config=runtime_config or {},
            )
            self._active[run_id] = state

            # 写 manifest 和 runtime-config（一次性）
            (run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "session_id": session_id,
                        "profile_id": profile_id,
                        "persona_id": persona_id,
                        "started_at_ms": now_ms,
                        "version": "0.1.0",
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "runtime-config.json").write_text(
                json.dumps(runtime_config or {}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("run started: %s", run_id)

    async def record(self, event: Event) -> None:
        """记录一个事件。

        仅记录当前活跃 Run 的事件；非 Run 范围（run_id 为 None 或已 finalize）
        直接跳过（session 级事件单独管理，v0.1 简化）。

        flush 策略：write 留锁内（防并发写交错），flush 按 _flush_interval_s
        时间窗口降频——高频音频事件下原本每秒 20-40 次 flush，现在合并。
        finalize_run 时强制 flush 保证落盘。
        """
        # 序列化在锁外做（json.dumps 是 CPU、不涉及共享状态）
        line = json.dumps(event.model_dump(), ensure_ascii=False) + "\n"
        async with self._lock:
            run_id = event.run_id
            if run_id is None or run_id not in self._active:
                # 非 Run 事件——跳过（session 级事件单独管理，v0.1 简化）
                return
            state = self._active[run_id]

            # 追加事件到 jsonl：write 在锁内 + to_thread（杜绝并发写同一句柄
            # 导致行交错，慢盘不卡事件循环）。
            await asyncio.to_thread(state.events_file.write, line)

            # flush 降频：距上次 flush 超过 _flush_interval_s 才真正 flush。
            # 进程崩溃最多丢一个窗口（0.5s）的事件——可接受，finalize 会强制 flush。
            now = time.monotonic()
            if now - state.last_flush_ts >= self._flush_interval_s:
                await asyncio.to_thread(state.events_file.flush)
                state.last_flush_ts = now

            # 更新指标（锁内——state 读改写需原子）
            self._update_metrics(state, event)

    def is_active(self, run_id: str) -> bool:
        """指定 Run 是否正在被记录（已 start_run，尚未 finalize）。

        替代直接读取 ``_active`` 私有属性。
        """
        return run_id in self._active

    async def finalize_run(
        self,
        run_id: str,
        *,
        status: str = "completed",
        errors: int = 0,
    ) -> Path | None:
        """结束一轮 Run，写出 metrics.json 和 transcript.json。

        Returns:
            run 目录路径，None 表示 run 不存在。
        """
        async with self._lock:
            state = self._active.pop(run_id, None)
            if state is None:
                return None

            now_ms = int(time.time() * 1000)
            state.metrics.ended_at_ms = now_ms
            state.metrics.total_duration_ms = now_ms - state.metrics.started_at_ms
            state.metrics.errors = errors
            state.metrics.cancelled = status in ("cancelled", "interrupted")

            # 写 metrics.json
            (state.run_dir / "metrics.json").write_text(
                json.dumps(state.metrics.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # 写 transcript.json
            transcript = {
                "run_id": run_id,
                "user": state.metrics.user_text,
                "assistant": state.metrics.assistant_text,
                "rounds": state.rounds,
            }
            (state.run_dir / "transcript.json").write_text(
                json.dumps(transcript, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # 关事件文件前强制 flush——record 的 flush 是降频的，
            # finalize 时必须把剩余缓冲落盘再关，否则尾事件丢失。
            state.events_file.flush()
            state.events_file.close()
            logger.info(
                "run finalized: %s status=%s duration=%dms",
                run_id,
                status,
                state.metrics.total_duration_ms,
            )
            return state.run_dir

    async def shutdown(self) -> None:
        """收尾所有未 finalize 的 Run。

        会话异常断开 / 进程退出时调用，避免 events.jsonl 文件句柄泄漏、
        以及 metrics.json/transcript.json 缺失。状态标记为 interrupted。
        """
        # 拷贝 key 避免 dict 在迭代中被 finalize_run 改动
        orphaned = list(self._active.keys())
        for run_id in orphaned:
            try:
                await self.finalize_run(run_id, status="interrupted")
            except Exception:
                logger.exception("shutdown: finalize orphan run failed: %s", run_id)

    # ------------------------------------------------------------------
    # 内部：指标更新
    # ------------------------------------------------------------------

    def _update_metrics(self, state: _RunState, event: Event) -> None:
        """根据事件类型更新指标。"""
        m = state.metrics
        elapsed = event.timestamp - m.started_at_ms

        if event.type == TRANSCRIPT_COMPLETED:
            m.user_text = event.payload.get("text", "")
            state.rounds.append({"role": "user", "text": m.user_text})

        elif event.type == LLM_TEXT_DELTA:
            text = event.payload.get("text", "")
            if text and m.first_text_ms is None:
                m.first_text_ms = max(0, elapsed)
            m.assistant_text += text

        elif event.type == LLM_TEXT_DONE:
            full_text = event.payload.get("full_text", "")
            # 如果 delta 没累积到（或为空），用 done 的 full_text 兜底
            if full_text and not m.assistant_text:
                m.assistant_text = full_text
            state.rounds.append(
                {
                    "role": "assistant",
                    "text": full_text,
                }
            )

        elif event.type == TTS_AUDIO_DELTA:
            # 垫音（filler=True）不计入延迟指标——此前 first_audio_ms≈0、
            # assistant_audio_samples 虚高，"首音延迟"在垫音开启时恒失真
            if event.payload.get("filler"):
                return
            if m.first_audio_ms is None:
                m.first_audio_ms = max(0, elapsed)
            m.assistant_audio_samples += event.payload.get("samples", 0)

        elif event.type == TTS_AUDIO_COMPLETED:
            pass  # 已在 delta 累计

        elif event.type in (AVATAR_SPEECH_FRAME, AVATAR_IDLE_FRAME):
            if m.first_frame_ms is None:
                m.first_frame_ms = max(0, elapsed)
            m.avatar_frames += 1

        elif event.type == AVATAR_DEGRADED:
            m.degradations += 1
            m.degraded_blocks[event.payload.get("from_block", "")] = event.payload.get(
                "to_block", ""
            )

        elif event.type == SESSION_STATE_CHANGED:
            to_state = event.payload.get("to", "")
            if to_state == "interrupting":
                m.interruptions += 1

        elif event.type == RESPONSE_INTERRUPTED:
            m.cancelled = True

        elif event.type == RESPONSE_DONE:
            m.cancelled = event.payload.get("interrupted", False)

        elif event.type == ARTIFACT_CREATED:
            state.artifacts.append(event.payload)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_run_dir(self, run_id: str) -> Path | None:
        """返回 run 目录路径（无论是否活跃）。"""
        if run_id in self._active:
            return self._active[run_id].run_dir
        path = self.root / run_id
        return path if path.exists() else None

    def list_runs(self) -> list[str]:
        """列出所有 run_id。"""
        return sorted(
            p.name for p in self.root.iterdir() if p.is_dir() and p.name.startswith("run_")
        )

    def load_metrics(self, run_id: str) -> dict[str, Any] | None:
        """加载某 run 的 metrics.json。"""
        path = self.root / run_id / "metrics.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def load_transcript(self, run_id: str) -> dict[str, Any] | None:
        """加载某 run 的 transcript.json。"""
        path = self.root / run_id / "transcript.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        """加载某 run 的所有事件。"""
        path = self.root / run_id / "events.jsonl"
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events


class _RunState:
    """单 Run 的内存状态。"""

    def __init__(
        self,
        run_id: str,
        session_id: str,
        profile_id: str,
        persona_id: str | None,
        started_at_ms: int,
        run_dir: Path,
        metrics: RunMetrics,
        events_file: Any,
        runtime_config: dict[str, Any],
    ) -> None:
        self.run_id = run_id
        self.session_id = session_id
        self.profile_id = profile_id
        self.persona_id = persona_id
        self.started_at_ms = started_at_ms
        self.run_dir = run_dir
        self.metrics = metrics
        self.events_file = events_file
        self.runtime_config = runtime_config
        self.rounds: list[dict[str, str]] = []
        self.artifacts: list[dict[str, Any]] = []
        # 上次 flush 的 monotonic 时间戳——record 按 _flush_interval_s 降频 flush
        self.last_flush_ts: float = 0.0
