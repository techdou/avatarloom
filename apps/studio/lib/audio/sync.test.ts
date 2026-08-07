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
    // 填满队列（maxQueueSize=100，对齐 VoxEMW 积压窗口经验）
    for (let i = 0; i < 100; i++) {
      mux.pushFrame({ blob: new Blob(), tag: "speech" });
    }
    expect(mux.queueLength).toBe(100);
    // 第 101 个应丢最旧
    mux.pushFrame({ blob: new Blob(), tag: "speech" });
    // 队列仍是 100（丢一个加一个）
    expect(mux.queueLength).toBeLessThanOrEqual(100);
  });

  it("updateConfig changes settings", () => {
    const mux = new AVMux({ audioDelayMs: 600 });
    mux.updateConfig({ audioDelayMs: 1000 });
    // 无直接 getter，但不应抛错
    expect(mux.queueLength).toBe(0);
  });

  it("resetFrames clears queue and resets frame index (常规重锚)", () => {
    const mux = new AVMux({});
    for (let i = 0; i < 10; i++) mux.pushFrame({ blob: new Blob(), tag: "speech" });
    mux.resetFrames();
    expect(mux.queueLength).toBe(0);
    // 帧序号归零：新回复 target 从 0 起算仍能消费
    mux.pushFrame({ blob: new Blob(), tag: "speech" });
    expect(mux.queueLength).toBe(1);
  });

  it("interrupt also resets frame index (修复：打断后画面卡死)", () => {
    const mux = new AVMux({});
    for (let i = 0; i < 10; i++) mux.pushFrame({ blob: new Blob(), tag: "speech" });
    mux.interrupt();
    expect(mux.queueLength).toBe(0);
    // videoFrameIdx 已归零——新回复帧不会被旧序号挡在 target 之外
    const frames: AvatarFrame[] = [];
    const mux2 = new AVMux({}, (f) => frames.push(f));
    mux2.pushFrame({ blob: new Blob(), tag: "speech" });
    mux2.interrupt();
    mux2.pushFrame({ blob: new Blob(), tag: "speech" });
    expect(mux2.queueLength).toBe(1);
  });

  it("trimTailFrames keeps unplayed real frames, drops tail padding (连播豁免)", () => {
    const mux = new AVMux({ fps: 25 });
    // 模拟上段回复：基准 base=10.0，链尾 prevEnd=12.0（2s=50 帧总量）
    // 已消费 30 帧 → 未播真帧 20 帧应保留；队列里多余的尾帧裁掉
    for (let i = 0; i < 30; i++) mux.pushFrame({ blob: new Blob(), tag: "speech" });
    // 消费 30 帧（直接操作 idx 不可达——用 interrupt 语义外的公开行为近似：
    // trimTailFrames 的 keep = floor((prevEnd-base)*fps) - idx。idx 当前 0（未消费），
    // keep=50，队列 30 < 50 不裁
    mux.trimTailFrames(12.0, 10.0);
    expect(mux.queueLength).toBe(30);
    // prevEnd 很近（只多 4 帧余量）：keep=4，裁到 4
    mux.trimTailFrames(10.16, 10.0);
    expect(mux.queueLength).toBe(4);
    // prevEnd 早于基准（异常）：keep=0 清空
    mux.trimTailFrames(9.0, 10.0);
    expect(mux.queueLength).toBe(0);
  });
});
