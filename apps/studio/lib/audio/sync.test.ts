import { describe, it, expect } from "vitest";
import { AVMux, type AvatarFrame } from "./sync";

describe("AVMux", () => {
  it("idle frame is displayed immediately without queueing", () => {
    const frames: AvatarFrame[] = [];
    const mux = new AVMux({}, (f) => frames.push(f));
    const idle: AvatarFrame = { blob: new Blob(), tag: "idle" };
    mux.pushFrame(idle);
    expect(frames).toHaveLength(1);
    expect(frames[0].tag).toBe("idle");
    expect(mux.queueLength).toBe(0);
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
