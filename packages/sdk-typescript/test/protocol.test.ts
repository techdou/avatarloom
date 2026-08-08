// 生成协议的完整性校验——守护 scripts/gen_protocol.py 的输出质量。
// 事件常量重复、状态机丢状态这类生成事故会在这里直接红灯。

import { describe, expect, it } from "vitest";

import * as events from "../src/generated/events";
import { SESSION_STATES } from "../src/generated/state";

describe("generated protocol constants", () => {
  it("事件类型常量不重复且命名符合 dot.lower_case 约定", () => {
    const values = Object.entries(events)
      .filter(([key, v]) => typeof v === "string" && key === key.toUpperCase())
      .map(([, v]) => v as string);
    expect(values.length).toBeGreaterThan(0);
    expect(new Set(values).size).toBe(values.length);
    for (const v of values) {
      expect(v).toMatch(/^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$/);
    }
  });

  it("状态机覆盖完整会话生命周期且无重复", () => {
    expect(SESSION_STATES).toEqual(
      expect.arrayContaining(["idle", "listening", "thinking", "speaking", "error", "closed"]),
    );
    expect(new Set(SESSION_STATES).size).toBe(SESSION_STATES.length);
  });
});
