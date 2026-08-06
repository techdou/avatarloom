/**
 * 会话运行时归约——SessionEvent 事件流 + 本轮里程碑计时。
 *
 * 纯函数、无 React 依赖，供 use-realtime-session 的 useReducer 使用。
 *
 * 设计要点：
 * - 事件流是下行 JSON 事件的本地滚动记录（ring buffer，上限 MAX_EVENTS）。
 * - 高频 delta 类事件（llm.text.delta / tts.audio.delta）不进事件流，只更新里程碑。
 * - "本轮"窗口：transcript.completed 到达时重置 timing 并以它为 t0；
 *   首个 llm delta / PCM / 视频帧各自只记首次，下一轮自动解锁。
 * - 二进制下行（0x01 帧 / 0x03 PCM）不进事件流——首包时刻由 milestone action 记录。
 */

export interface SessionEvent {
  type: string;
  /** 本地接收时刻（ms epoch） */
  ts: number;
  /** payload 摘要（已截断），供事件流列表展示 */
  summary: string;
}

export interface RoundTiming {
  /** transcript.completed 时刻（用户说完）。本轮 t0 基准。 */
  transcriptTs: number | null;
  /** llm.text.delta 首次时刻 */
  firstDeltaTs: number | null;
  /** 首个下行 PCM（0x03）时刻 */
  firstPcmTs: number | null;
  /** 首个下行视频帧（0x01）时刻 */
  firstFrameTs: number | null;
}

export interface SessionRuntime {
  sessionState: string;
  sessionId: string | null;
  /** 最近一次 run.started 时刻（仅展示；payload 不带 run_id，不做窗口边界） */
  lastRunAt: number | null;
  timing: RoundTiming;
  events: SessionEvent[];
}

export const MAX_EVENTS = 200;

const EMPTY_TIMING: RoundTiming = {
  transcriptTs: null,
  firstDeltaTs: null,
  firstPcmTs: null,
  firstFrameTs: null,
};

export const INITIAL_RUNTIME: SessionRuntime = {
  sessionState: "idle",
  sessionId: null,
  lastRunAt: null,
  timing: EMPTY_TIMING,
  events: [],
};

export type RuntimeAction =
  | { kind: "sessionStarted"; sessionId: string; state: string; ts: number }
  | { kind: "stateChanged"; to: string; ts: number }
  | {
      kind: "event";
      type: string;
      summary: string;
      ts: number;
      /** AL-P1-005：orchestrator 以新 run_id 重发的 transcript.completed——
          只进事件流，不重置本轮 timing（t0 已由原始事件锚定）。 */
      reEmitted?: boolean;
    }
  | { kind: "milestone"; key: "firstDeltaTs" | "firstPcmTs" | "firstFrameTs"; ts: number }
  | { kind: "disconnected" };

function pushEvent(events: SessionEvent[], ev: SessionEvent): SessionEvent[] {
  const next = [...events, ev];
  return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
}

export function sessionRuntimeReducer(
  state: SessionRuntime,
  action: RuntimeAction
): SessionRuntime {
  switch (action.kind) {
    case "sessionStarted":
      return {
        ...INITIAL_RUNTIME,
        sessionState: action.state,
        sessionId: action.sessionId,
        timing: { ...EMPTY_TIMING },
        events: [
          { type: "session.started", ts: action.ts, summary: action.sessionId },
        ],
      };

    case "stateChanged": {
      if (action.to === state.sessionState) return state;
      return {
        ...state,
        sessionState: action.to,
        events: pushEvent(state.events, {
          type: "session.state_changed",
          ts: action.ts,
          summary: `${state.sessionState} → ${action.to}`,
        }),
      };
    }

    case "event": {
      const ev: SessionEvent = { type: action.type, ts: action.ts, summary: action.summary };
      // transcript.completed 开启新一轮：重置 timing 并锚定 t0。
      // 重发副本（re_emitted）只进事件流，不动 timing——t0 已由原始事件锚定。
      if (action.type === "transcript.completed" && !action.reEmitted) {
        return {
          ...state,
          timing: { ...EMPTY_TIMING, transcriptTs: action.ts },
          events: pushEvent(state.events, ev),
        };
      }
      if (action.type === "run.started") {
        return { ...state, lastRunAt: action.ts, events: pushEvent(state.events, ev) };
      }
      return { ...state, events: pushEvent(state.events, ev) };
    }

    case "milestone": {
      // 首轮锁定；新一轮（transcript.completed 重置 timing）后自动解锁
      if (state.timing[action.key] != null) return state;
      return {
        ...state,
        timing: { ...state.timing, [action.key]: action.ts },
      };
    }

    case "disconnected":
      // 事件流保留——断连后仍可回看本轮调试信息
      return { ...state, sessionState: "idle" };

    default:
      return state;
  }
}

/** 生成事件摘要；返回 null 表示该事件不进事件流（高频/心跳类）。 */
export function summarizeEvent(
  type: string,
  payload: Record<string, unknown> | undefined
): string | null {
  const p = payload ?? {};
  switch (type) {
    case "llm.text.delta":
    case "tts.audio.delta":
    case "pong":
      return null;
    case "transcript.completed":
      return truncate(String(p.text ?? ""), 60);
    case "llm.text.done": {
      const full = String(p.full_text ?? "");
      return `完整回复 ${full.length} 字`;
    }
    case "vision.result":
      return truncate(String(p.description ?? ""), 60);
    case "vision.request":
      return "触发词命中，请求截帧";
    case "tts.audio.completed":
      return "TTS 音频生成完毕";
    case "avatar.video.ready":
      return truncate(String(p.path ?? p.video_path ?? "视频就绪"), 60);
    case "persona.changed":
      return truncate(String(p.persona_id ?? ""), 40);
    case "run.started":
      return "新 Run 开始";
    case "response.done":
      return "本轮回复完成";
    case "error":
      return truncate(String(p.message ?? "unknown"), 80);
    default:
      return truncate(JSON.stringify(p), 60);
  }
}

/** 提取"本轮"事件子集：从最近的 transcript.completed / run.started（取更靠后者）起。 */
export function currentRoundEvents(events: SessionEvent[]): SessionEvent[] {
  let start = -1;
  for (let i = events.length - 1; i >= 0; i--) {
    const t = events[i].type;
    if (t === "transcript.completed" || t === "run.started") {
      start = i;
      break;
    }
  }
  return start >= 0 ? events.slice(start) : events;
}

/** 本轮里程碑延迟（相对 t0 的 ms）。t0 未定返回 null。 */
export function roundLatencies(timing: RoundTiming): {
  firstTextMs: number | null;
  firstAudioMs: number | null;
  firstFrameMs: number | null;
} {
  const t0 = timing.transcriptTs;
  if (t0 == null) return { firstTextMs: null, firstAudioMs: null, firstFrameMs: null };
  const rel = (ts: number | null) => (ts == null ? null : Math.max(0, ts - t0));
  return {
    firstTextMs: rel(timing.firstDeltaTs),
    firstAudioMs: rel(timing.firstPcmTs),
    firstFrameMs: rel(timing.firstFrameTs),
  };
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}
