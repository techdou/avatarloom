/**
 * 音画同步管理器。
 *
 * 音频是主时钟（docs/02）。视频帧从属音频播放位置。
 *
 * 策略（参考 VoxEMW）：
 * - Speech Frame 按音频位置消费
 * - Idle Frame 直接显示，不进队列
 * - 视频落后允许跳帧（drop_oldest）
 * - 视频不阻塞音频
 * - 打断时清空帧队列
 */

export type FrameTag = "idle" | "speech";

export interface AvatarFrame {
  /** JPEG/PNG 二进制 */
  blob: Blob | ArrayBuffer;
  /** 帧类型 */
  tag: FrameTag;
  /** 对应音频时间戳（可选，用于精确同步） */
  audioTimestamp?: number;
}

export interface SyncConfig {
  audioDelayMs: number;
  videoLagFrames: number;
  maxVideoBehindMs: number;
  dropPolicy: "drop_oldest_video" | "drop_newest_video" | "block";
}

export class AVMux {
  private frameQueue: AvatarFrame[] = [];
  private maxQueueSize = 25;
  private config: SyncConfig;
  private onFrame?: (frame: AvatarFrame) => void;
  private consuming = false;

  constructor(config: Partial<SyncConfig> = {}, onFrame?: (f: AvatarFrame) => void) {
    this.config = {
      audioDelayMs: 600,
      videoLagFrames: 0,
      maxVideoBehindMs: 1000,
      dropPolicy: "drop_oldest_video",
      ...config,
    };
    this.onFrame = onFrame;
  }

  /** 入队一帧（从 Gateway 收到的 Avatar JPEG）。 */
  pushFrame(frame: AvatarFrame) {
    // Idle frame 直接显示，不进队列
    if (frame.tag === "idle") {
      this.onFrame?.(frame);
      return;
    }
    // Speech frame 入队，按 dropPolicy 处理满队
    if (this.frameQueue.length >= this.maxQueueSize) {
      if (this.config.dropPolicy === "drop_oldest_video") {
        this.frameQueue.shift();
      } else if (this.config.dropPolicy === "drop_newest_video") {
        return; // 丢最新（不入队）
      }
      // block 策略理论上不会满（生产者被阻塞），这里降级丢最旧
      else {
        this.frameQueue.shift();
      }
    }
    this.frameQueue.push(frame);
    this._scheduleConsume();
  }

  /** 打断——清空队列。 */
  interrupt() {
    this.frameQueue = [];
  }

  /** 当前队列长度。 */
  get queueLength() {
    return this.frameQueue.length;
  }

  /** 更新配置。 */
  updateConfig(cfg: Partial<SyncConfig>) {
    this.config = { ...this.config, ...cfg };
  }

  private _scheduleConsume() {
    if (this.consuming) return;
    this.consuming = true;
    // 用 requestAnimationFrame 节流消费（~16ms）
    requestAnimationFrame(() => {
      this.consuming = false;
      // 消费一批（按 videoLagFrames 延迟）
      const lag = this.config.videoLagFrames;
      while (this.frameQueue.length > lag) {
        const frame = this.frameQueue.shift()!;
        this.onFrame?.(frame);
      }
    });
  }
}
