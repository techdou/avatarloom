import { describe, it, expect } from "vitest";
import {
  sessionRuntimeReducer,
  summarizeEvent,
  currentRoundEvents,
  roundLatencies,
  INITIAL_RUNTIME,
  MAX_EVENTS,
  type SessionRuntime,
  type SessionEvent,
} from "./events";

const T0 = 1_000_000;

function reduce(state: SessionRuntime, ...actions: Parameters<typeof sessionRuntimeReducer>[1][]) {
  return actions.reduce(sessionRuntimeReducer, state);
}

describe("sessionRuntimeReducer", () => {
  it("sessionStarted 重置全部并压入首条事件", () => {
    const prev: SessionRuntime = {
      ...INITIAL_RUNTIME,
      sessionState: "speaking",
      events: [{ type: "transcript.completed", ts: T0, summary: "旧" }],
    };
    const next = sessionRuntimeReducer(prev, {
      kind: "sessionStarted",
      sessionId: "ses_abc",
      state: "idle",
      ts: T0,
    });
    expect(next.sessionId).toBe("ses_abc");
    expect(next.sessionState).toBe("idle");
    expect(next.events).toHaveLength(1);
    expect(next.events[0].type).toBe("session.started");
    expect(next.timing.transcriptTs).toBeNull();
  });

  it("transcript.completed 开启新一轮：重置 timing 并锚定 t0", () => {
    const state = reduce(INITIAL_RUNTIME, {
      kind: "event",
      type: "transcript.completed",
      summary: "你好",
      ts: T0,
    });
    expect(state.timing.transcriptTs).toBe(T0);
    expect(state.events.at(-1)?.summary).toBe("你好");
  });

  it("milestone 首轮锁定；新一轮后自动解锁", () => {
    let state = reduce(INITIAL_RUNTIME, { kind: "event", type: "transcript.completed", summary: "", ts: T0 });
    state = reduce(state, { kind: "milestone", key: "firstDeltaTs", ts: T0 + 300 });
    // 重复 milestone 不覆盖
    state = reduce(state, { kind: "milestone", key: "firstDeltaTs", ts: T0 + 999 });
    expect(state.timing.firstDeltaTs).toBe(T0 + 300);
    // 新一轮：transcript.completed 重置后 milestone 重新可记
    state = reduce(state, { kind: "event", type: "transcript.completed", summary: "", ts: T0 + 5000 });
    expect(state.timing.firstDeltaTs).toBeNull();
    state = reduce(state, { kind: "milestone", key: "firstDeltaTs", ts: T0 + 5200 });
    expect(state.timing.firstDeltaTs).toBe(T0 + 5200);
  });

  it("stateChanged 去抖并记录 from → to", () => {
    let state = reduce(INITIAL_RUNTIME, { kind: "stateChanged", to: "listening", ts: T0 });
    const len = state.events.length;
    state = reduce(state, { kind: "stateChanged", to: "listening", ts: T0 + 1 });
    expect(state.events.length).toBe(len); // 相同状态不压事件
    expect(state.events[0].summary).toBe("idle → listening");
  });

  it("事件流 ring buffer 截断到 MAX_EVENTS", () => {
    let state = INITIAL_RUNTIME;
    for (let i = 0; i < MAX_EVENTS + 30; i++) {
      state = reduce(state, { kind: "event", type: "vision.request", summary: `第${i}次`, ts: T0 + i });
    }
    expect(state.events.length).toBe(MAX_EVENTS);
    expect(state.events[0].summary).toBe("第30次");
  });

  it("disconnected 回到 idle 但保留事件流", () => {
    let state = reduce(INITIAL_RUNTIME, { kind: "event", type: "vision.request", summary: "x", ts: T0 });
    state = reduce(state, { kind: "disconnected" });
    expect(state.sessionState).toBe("idle");
    expect(state.events.length).toBe(1);
  });
});

describe("summarizeEvent", () => {
  it("高频/心跳事件返回 null（不进事件流）", () => {
    expect(summarizeEvent("llm.text.delta", { text: "你" })).toBeNull();
    expect(summarizeEvent("tts.audio.delta", {})).toBeNull();
    expect(summarizeEvent("pong", {})).toBeNull();
  });

  it("transcript/error 摘要截断", () => {
    expect(summarizeEvent("transcript.completed", { text: "x".repeat(100) })).toHaveLength(61);
    expect(summarizeEvent("error", { message: "boom" })).toBe("boom");
  });

  it("llm.text.done 汇报字数", () => {
    expect(summarizeEvent("llm.text.done", { full_text: "你好世界" })).toBe("完整回复 4 字");
  });
});

describe("currentRoundEvents / roundLatencies", () => {
  it("从最近的 transcript.completed 切出本轮", () => {
    const events: SessionEvent[] = [
      { type: "session.started", ts: 1, summary: "" },
      { type: "transcript.completed", ts: 2, summary: "第一轮" },
      { type: "response.done", ts: 3, summary: "" },
      { type: "transcript.completed", ts: 4, summary: "第二轮" },
      { type: "vision.request", ts: 5, summary: "" },
    ];
    const round = currentRoundEvents(events);
    expect(round[0].summary).toBe("第二轮");
    expect(round).toHaveLength(2);
  });

  it("延迟相对 t0 计算；t0 未定返回 null", () => {
    const timing = { transcriptTs: 100, firstDeltaTs: 350, firstPcmTs: 900, firstFrameTs: null };
    expect(roundLatencies(timing)).toEqual({ firstTextMs: 250, firstAudioMs: 800, firstFrameMs: null });
    expect(roundLatencies({ transcriptTs: null, firstDeltaTs: 1, firstPcmTs: 2, firstFrameTs: 3 }).firstTextMs).toBeNull();
  });
});
