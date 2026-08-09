"""Index RunRecorder filesystem outputs for the Studio query API."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def load_run(runs_root: str | Path, run_id: str) -> dict[str, Any] | None:
    run_dir = Path(runs_root) / run_id
    manifest = _read_json(run_dir / "manifest.json")
    if not manifest:
        return None
    metrics = _read_json(run_dir / "metrics.json")
    transcript = _read_json(run_dir / "transcript.json")
    ended_at = _timestamp(metrics.get("ended_at_ms"))
    return {
        "id": str(manifest.get("run_id") or run_id),
        "session_id": str(manifest.get("session_id") or ""),
        "profile_id": manifest.get("profile_id"),
        "persona_id": manifest.get("persona_id"),
        "status": metrics.get("status") or ("completed" if ended_at else "running"),
        "metrics": metrics or None,
        "run_dir": run_id,
        "user_text": transcript.get("user") or metrics.get("user_text") or "",
        "assistant_text": transcript.get("assistant") or metrics.get("assistant_text") or "",
        "started_at": _timestamp(manifest.get("started_at_ms")) or datetime.now(UTC),
        "ended_at": ended_at,
    }


def list_run_files(runs_root: str | Path) -> list[dict[str, Any]]:
    root = Path(runs_root)
    if not root.exists():
        return []
    runs = [
        item
        for directory in root.iterdir()
        if directory.is_dir() and (item := load_run(root, directory.name)) is not None
    ]
    return sorted(runs, key=lambda item: item["started_at"], reverse=True)


def list_session_files(runs_root: str | Path) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in list_run_files(runs_root):
        # 损坏/手工创建的 manifest 不能被折叠成一个 id="" 的伪会话。
        if run["session_id"]:
            grouped.setdefault(run["session_id"], []).append(run)
    sessions_by_id: dict[str, dict[str, Any]] = {}
    for session_id, runs in grouped.items():
        started_at = min(run["started_at"] for run in runs)
        ended_values = [run["ended_at"] for run in runs if run["ended_at"] is not None]
        active = any(run["ended_at"] is None for run in runs)
        sessions_by_id[session_id] = {
            "id": session_id,
            "avatar_id": None,
            # list_run_files 已按 started_at 降序，首项才是会话的最新上下文。
            "profile_id": runs[0]["profile_id"],
            "persona_id": runs[0]["persona_id"],
            "status": "active" if active else "closed",
            "started_at": started_at,
            "ended_at": None if active else max(ended_values, default=started_at),
        }

    sessions_root = Path(runs_root) / "_sessions"
    if sessions_root.exists():
        for path in sessions_root.glob("*.json"):
            data = _read_json(path)
            session_id = str(data.get("id") or path.stem)
            existing = sessions_by_id.get(session_id, {})
            sessions_by_id[session_id] = {
                "id": session_id,
                "avatar_id": None,
                "profile_id": data.get("profile_id") or existing.get("profile_id"),
                "persona_id": data.get("persona_id") or existing.get("persona_id"),
                "status": data.get("status") or existing.get("status") or "active",
                "started_at": _timestamp(data.get("started_at_ms"))
                or existing.get("started_at")
                or datetime.now(UTC),
                "ended_at": _timestamp(data.get("ended_at_ms")) or existing.get("ended_at"),
            }
    return sorted(sessions_by_id.values(), key=lambda item: item["started_at"], reverse=True)
