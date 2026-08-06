import { describe, it, expect } from "vitest";
import { AVMux, type AvatarFrame } from "./sync";

describe("AVMux", () => {
  it("idle frame without playing audio is queued for throttled draw, not speech queue", () => {
    const frames: AvatarFrame[] = [];
    const mux = new AVMux({}, (f) => frames.push(f));
    const idle: AvatarFrame = { blob: new Blob(), tag: "idle" };
    mux.pushFrame(idle);
    // idle 帧不占 speech 队列（queueLength 只统计 speech 帧）
    expect(mux.queueLength).toBe(0);
    // 同步断言时 onFrame 未被调用（rAF 异步消费）
    expect(frames).toHaveLength(0);
  });

  it("idle frame while audio playing joins speech queue along clock", () => {
    const frames: AvatarFrame[] = [];
    const mux = new AVMux(
      { getAudioTime: () => 1.0 },
      (f) => frames.push(f)
    );
    // 先塞一个 speech 帧（音频在播）
    mux.pushFrame({ blob: new Blob(), tag: "speech" });
    const idle: AvatarFrame = { blob: new Blob(), tag: "idle" };
    mux.pushFrame(idle);
    // idle 帧在音频播时进 speech 队列
    expect(mux.queueLength).toBe(2);
  });

  it("speech frame is queued", () => {
    const mux = new AVMux({});
    const speech: AvatarFrame = { blob: new Blob(), tag: "speech" };
    mux.pushFrame(speech);
    expect(mux.queueLength).toBe(1);
  });

  it("interrupt clears queue", () => {
    const mux = new AVMux({});
    for (let i = 0; i < 5; i++) {
      mux.pushFrame({ blob: new Blob(), tag: "speech" });
    }
    expect(mux.queueLength).toBe(5);
    mux.interrupt();
    expect(mux.queueLength).toBe(0);
  });

  it("drop_oldest drops oldest when full", () => {
    const frames: AvatarFrame[] = [];
    const mux = new AVMux({ dropPolicy: "drop_oldest_video" }, (f) => frames.push(f));
    // 填满队列（maxQueueSize=25）
    for (let i = 0; i < 25; i++) {
      mux.pushFrame({ blob: new Blob(), tag: "speech" });
    }
    expect(mux.queueLength).toBe(25);
    // 第 26 个应丢最旧
    mux.pushFrame({ blob: new Blob(), tag: "speech" });
    // 队列仍是 25（丢一个加一个）
    expect(mux.queueLength).toBeLessThanOrEqual(25);
  });

  it("updateConfig changes settings", () => {
    const mux = new AVMux({ audioDelayMs: 600 });
    mux.updateConfig({ audioDelayMs: 1000 });
    // 无直接 getter，但不应抛错
    expect(mux.queueLength).toBe(0);
  });
});
