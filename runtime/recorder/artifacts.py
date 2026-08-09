"""Artifact Writer。

把 Run 过程中产生的产物（音频、视频、图片、文本）写到文件系统，
并记录引用。

目录布局：
    artifacts/
    ├── audio/
    │   └── <run_id>/
    │       ├── user_input.wav       用户输入音频
    │       └── assistant_output.wav 助手输出音频
    ├── video/
    │   └── <run_id>/
    │       └── frames/              视频帧序列
    └── text/
        └── <run_id>/
            ├── transcript.txt
            └── llm_response.txt
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Literal

from avatarloom_protocol import ARTIFACT_CREATED, Event
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ArtifactKind = Literal["audio", "video", "image", "text", "json", "config"]


class ArtifactRecord(BaseModel):
    """Artifact 元数据记录。"""

    artifact_id: str
    run_id: str
    kind: ArtifactKind
    path: str = Field(description="相对 artifacts root 的路径")
    mime_type: str | None = None
    size_bytes: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactWriter:
    """写 Artifact 到文件系统并维护索引。"""

    def __init__(self, root: str | Path = "./data/artifacts") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._emit_fn: Any = None
        # fire-and-forget emit task 的引用——持引用防 GC，定期清理已完成的
        self._pending_tasks: list[Any] = []

    def set_emit_fn(self, emit_fn: Any) -> None:
        """注入事件发射器——写完 artifact 后 emit artifact.created。"""
        self._emit_fn = emit_fn

    def write_bytes(
        self,
        run_id: str,
        kind: ArtifactKind,
        filename: str,
        data: bytes,
        *,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> ArtifactRecord:
        """写字节数据。"""
        rel_dir = f"{kind}/{run_id}"
        abs_dir = self.root / rel_dir
        abs_dir.mkdir(parents=True, exist_ok=True)
        abs_path = abs_dir / filename
        abs_path.write_bytes(data)

        record = ArtifactRecord(
            artifact_id=f"art_{uuid.uuid4().hex[:20]}",
            run_id=run_id,
            kind=kind,
            path=f"{rel_dir}/{filename}",
            mime_type=mime_type,
            size_bytes=len(data),
            metadata=metadata or {},
        )
        self._write_index(run_id, record)
        return record

    def write_text(
        self,
        run_id: str,
        kind: ArtifactKind,
        filename: str,
        text: str,
        *,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        """写文本数据。"""
        return self.write_bytes(
            run_id,
            kind,
            filename,
            text.encode("utf-8"),
            mime_type=mime_type or "text/plain; charset=utf-8",
            metadata=metadata,
        )

    def write_json(
        self,
        run_id: str,
        filename: str,
        obj: Any,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        """写 JSON。"""
        text = json.dumps(obj, indent=2, ensure_ascii=False)
        return self.write_text(
            run_id,
            "json",
            filename,
            text,
            mime_type="application/json",
            metadata=metadata,
        )

    def resolve_path(self, relative_path: str) -> Path:
        """把相对路径解析为绝对路径。"""
        # 防目录穿越
        if ".." in relative_path:
            raise ValueError(f"Relative path contains '..': {relative_path}")
        return self.root / relative_path

    def list_artifacts(self, run_id: str) -> list[ArtifactRecord]:
        """列出某 run 的所有 artifact。"""
        index_path = self.root / f"index_{run_id}.json"
        if not index_path.exists():
            return []
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return [ArtifactRecord(**item) for item in data]

    # ---- 内部 ----

    def _write_index(self, run_id: str, record: ArtifactRecord) -> None:
        """维护每 run 的 artifact 索引。"""
        index_path = self.root / f"index_{run_id}.json"
        existing: list[dict[str, Any]] = []
        if index_path.exists():
            existing = json.loads(index_path.read_text(encoding="utf-8"))
        existing.append(record.model_dump())
        index_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

        # emit artifact.created 事件
        if self._emit_fn is not None:
            event = Event(
                type=ARTIFACT_CREATED,
                session_id="(artifact)",
                source="recorder.artifacts",
                run_id=run_id,
                payload=record.model_dump(),
            )
            # emit_fn 可能是 async；ArtifactWriter 是同步类，用 fire-and-forget task
            import asyncio

            coro = self._emit_fn(event)
            if asyncio.iscoroutine(coro):
                try:
                    loop = asyncio.get_running_loop()
                    task = loop.create_task(coro)

                    def _log_if_failed(t: asyncio.Task) -> None:
                        if t.cancelled():
                            return
                        exc = t.exception()
                        if exc is not None:
                            logging.getLogger(__name__).warning(
                                "artifact.created emit failed: %s", exc, exc_info=exc
                            )

                    task.add_done_callback(_log_if_failed)
                    self._pending_tasks.append(task)  # 持引用防 GC

                    def _discard(t: asyncio.Task) -> None:
                        # 完成后从引用列表移除，防只增不减的内存泄漏
                        try:
                            self._pending_tasks.remove(t)
                        except ValueError:
                            pass

                    task.add_done_callback(_discard)
                except RuntimeError:
                    # 无运行中 loop（block 在 to_thread 里调 write）——降级：不 emit
                    logging.getLogger(__name__).debug(
                        "artifact emit skipped: no running loop (thread context)"
                    )
