#!/usr/bin/env python
"""从 Pydantic 事件模型生成 JSON Schema 和 TypeScript 类型。

用法:
    uv run python scripts/gen_protocol.py

输出:
    packages/sdk-typescript/src/generated/events.json     — 所有事件 JSON Schema
    packages/sdk-typescript/src/generated/events.ts       — TypeScript 类型
    packages/sdk-typescript/src/generated/state.ts        — 状态机类型
"""

from __future__ import annotations

import json
import sys
import types
import typing
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

# 让脚本能在 `uv run python scripts/gen_protocol.py` 下工作
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "protocol" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "sdk-python" / "src"))

from avatarloom_protocol import State  # noqa: E402
from avatarloom_protocol import payloads as P  # noqa: E402
from avatarloom_protocol.envelope import (  # noqa: E402
    ARTIFACT_CREATED,
    AUDIO_APPENDED,
    AUDIO_INTERRUPTED,
    AVATAR_DEGRADED,
    AVATAR_IDLE_FRAME,
    AVATAR_RESET,
    AVATAR_SPEECH_FRAME,
    BLOCK_ERROR,
    BLOCK_HEALTH,
    BLOCK_READY,
    BLOCK_SETUP,
    LLM_ERROR,
    LLM_TEXT_DELTA,
    LLM_TEXT_DONE,
    PERSONA_CHANGED,
    RESPONSE_DONE,
    RESPONSE_INTERRUPTED,
    RESPONSE_STARTED,
    RUN_COMPLETED,
    RUN_METRICS,
    RUN_STARTED,
    SESSION_CLOSED,
    SESSION_ERROR,
    SESSION_STARTED,
    SESSION_STATE_CHANGED,
    SPEECH_DETECTED,
    SPEECH_ENDED,
    TRANSCRIPT_COMPLETED,
    TRANSCRIPT_PARTIAL,
    TTS_AUDIO_COMPLETED,
    TTS_AUDIO_DELTA,
    TTS_ERROR,
    VISION_RESULT,
)
from pydantic import BaseModel  # noqa: E402

# ---------------------------------------------------------------------------
# 事件类型 -> payload 模型映射
# ---------------------------------------------------------------------------

EVENT_PAYLOAD_MAP: dict[str, type[BaseModel]] = {
    SESSION_STARTED: P.SessionStartedPayload,
    SESSION_CLOSED: P.SessionClosedPayload,
    SESSION_STATE_CHANGED: P.SessionStateChangedPayload,
    SESSION_ERROR: P.SessionErrorPayload,
    AUDIO_APPENDED: P.AudioAppendedPayload,
    AUDIO_INTERRUPTED: P.AudioInterruptedPayload,
    SPEECH_DETECTED: P.SpeechDetectedPayload,
    SPEECH_ENDED: P.SpeechEndedPayload,
    TRANSCRIPT_COMPLETED: P.TranscriptCompletedPayload,
    TRANSCRIPT_PARTIAL: P.TranscriptPartialPayload,
    LLM_TEXT_DELTA: P.LlmTextDeltaPayload,
    LLM_TEXT_DONE: P.LlmTextDonePayload,
    LLM_ERROR: P.SessionErrorPayload,  # LLM 错误复用 SessionError 结构
    TTS_AUDIO_DELTA: P.TtsAudioDeltaPayload,
    TTS_AUDIO_COMPLETED: P.TtsAudioCompletedPayload,
    TTS_ERROR: P.SessionErrorPayload,
    AVATAR_SPEECH_FRAME: P.AvatarFramePayload,
    AVATAR_IDLE_FRAME: P.AvatarFramePayload,
    AVATAR_RESET: P.AvatarResetPayload,
    AVATAR_DEGRADED: P.AvatarDegradedPayload,
    VISION_RESULT: P.VisionResultPayload,
    PERSONA_CHANGED: P.PersonaChangedPayload,
    RESPONSE_STARTED: P.ResponseStartedPayload,
    RESPONSE_DONE: P.ResponseDonePayload,
    RESPONSE_INTERRUPTED: P.ResponseInterruptedPayload,
    BLOCK_SETUP: P.BlockSetupPayload,
    BLOCK_READY: P.BlockReadyPayload,
    BLOCK_ERROR: P.BlockErrorPayload,
    BLOCK_HEALTH: P.BlockHealthPayload,
    RUN_STARTED: P.RunStartedPayload,
    RUN_METRICS: P.RunMetricsPayload,
    RUN_COMPLETED: P.RunCompletedPayload,
    ARTIFACT_CREATED: P.ArtifactPayload,
}


def to_camel_case(snake: str) -> str:
    """snake_case -> camelCase。"""
    parts = snake.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def pydantic_to_ts(model: type[BaseModel]) -> str:
    """把单个 Pydantic 模型转成 TS interface（简化版，手写规则）。"""
    from pydantic.fields import FieldInfo

    lines: list[str] = []
    lines.append(f"export interface {model.__name__} {{")
    hints = get_type_hints(model)
    for fname, ftype in hints.items():
        field_info: FieldInfo = model.model_fields[fname]  # type: ignore[assignment]
        required = field_info.is_required()
        ts_type = _py_type_to_ts(ftype)
        opt = "" if required else "?"
        lines.append(f"  {to_camel_case(fname)}{opt}: {ts_type};")
    lines.append("  [key: string]: unknown;")  # extra=allow
    lines.append("}")
    return "\n".join(lines)


def _py_type_to_ts(py_type: object) -> str:
    """Python 类型 -> TS 类型（简化映射）。"""
    if py_type is str:
        return "string"
    if py_type is int:
        return "number"
    if py_type is float:
        return "number"
    if py_type is bool:
        return "boolean"
    if py_type is Any or py_type is typing.Any:  # type: ignore[arg-type]
        return "unknown"

    origin = get_origin(py_type)
    args = get_args(py_type)

    if origin is Union or (
        hasattr(types, "UnionType") and isinstance(py_type, types.UnionType)
    ):
        # Optional / Union
        non_none = [a for a in args if a is not type(None)]
        ts_parts = [_py_type_to_ts(a) for a in non_none]
        nullable = len(non_none) < len(args)
        result = " | ".join(ts_parts)
        if nullable:
            result += " | null"
        return result
    if origin is list or origin is list:  # type: ignore[attr-defined]
        if args:
            return f"Array<{_py_type_to_ts(args[0])}>"
        return "unknown[]"
    if origin is dict or origin is dict:  # type: ignore[attr-defined]
        if args and args[1] is not Any:
            return f"Record<string, {_py_type_to_ts(args[1])}>"
        return "Record<string, unknown>"
    if origin is Literal:
        # Literal["a", "b"] -> "a" | "b"
        return " | ".join(
            f'"{a}"' if isinstance(a, str) else str(a) for a in args
        )
    return "unknown"


def generate_state_ts() -> str:
    """生成状态机 TS 类型。"""
    states = " | ".join(f'"{s.value}"' for s in State)
    return f"""// AUTO-GENERATED by scripts/gen_protocol.py — DO NOT EDIT
// 源：packages/protocol/src/avatarloom_protocol/state.py

export type SessionState = {states};

export const SESSION_STATES: SessionState[] = [
{chr(10).join(f'  "{s.value}",' for s in State)}
];

export interface StateTransitionResult {{
  from_state: SessionState;
  to_state: SessionState;
  trigger: string;
}}
"""


def generate_events_ts() -> str:
    """生成事件类型 TS。"""
    header = (
        "// AUTO-GENERATED by scripts/gen_protocol.py — DO NOT EDIT\n"
        "// 源：packages/protocol/src/avatarloom_protocol/{envelope,payloads}.py\n\n"
    )

    # 事件类型常量
    type_lines: list[str] = ["// 事件类型常量"]
    for event_type in sorted(EVENT_PAYLOAD_MAP.keys()):
        const_name = event_type.upper().replace(".", "_")
        type_lines.append(f'export const {const_name} = "{event_type}" as const;')

    # Event Envelope
    envelope_ts = """
export interface EventEnvelope {
  id: string;
  type: string;
  session_id: string;
  run_id: string | null;
  timestamp: number;
  source: string;
  sequence: number;
  payload: Record<string, unknown>;
}

export type Event = EventEnvelope;"""

    # Payload interfaces（去重，多个事件类型可能共享同一 payload 结构）
    payload_models = sorted(set(EVENT_PAYLOAD_MAP.values()), key=lambda m: m.__name__)
    payload_ts = "\n\n".join(pydantic_to_ts(m) for m in payload_models)

    return header + "\n".join(type_lines) + "\n" + envelope_ts + "\n\n" + payload_ts + "\n"


def main() -> int:
    out_dir = ROOT / "packages" / "sdk-typescript" / "src" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)

    # events.ts
    (out_dir / "events.ts").write_text(generate_events_ts(), encoding="utf-8")
    # state.ts
    (out_dir / "state.ts").write_text(generate_state_ts(), encoding="utf-8")
    # events.json（JSON Schema 汇总，供 Control API 校验用）
    schemas = {
        event_type: payload.model_json_schema()
        for event_type, payload in EVENT_PAYLOAD_MAP.items()
    }
    (out_dir / "events.json").write_text(
        json.dumps(schemas, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"✓ 生成协议类型到 {out_dir}")
    print(f"  - events.ts ({len(EVENT_PAYLOAD_MAP)} 事件类型)")
    print(f"  - state.ts ({len(list(State))} 状态)")
    print("  - events.json (JSON Schema)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
