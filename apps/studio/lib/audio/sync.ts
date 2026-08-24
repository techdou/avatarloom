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
  /** 视频帧率（FlashHead 25fps） */
  fps?: number;
  /** 音频播放位置回调（秒，相对本回复起点）。缺省时退化为 rAF 按序消费。 */
  getAudioTime?: () => number;
}

export class AVMux {
  private frameQueue: AvatarFrame[] = [];
  private idleQueue: AvatarFrame[] = [];
  // 4s 窗口（对齐 VoxEMW 经验：VoxCPM2 合成 ~2x 实时，帧必然积压 3-4s；
  // 25 帧=1s 的窗口在真实链路上会一路 drop_oldest，口型同步但画面顿挫）
  private maxQueueSize = 100;
  private config: SyncConfig;
  private onFrame?: (frame: AvatarFrame) => void;
  private consuming = false;
  /** 已消费帧序号（用于按音频位置对齐） */
  private videoFrameIdx = 0;
  private lastIdleDrawAt = 0;

  constructor(config: Partial<SyncConfig> = {}, onFrame?: (f: AvatarFrame) => void) {
    this.config = {
      audioDelayMs: 600,
      videoLagFrames: 0,
      maxVideoBehindMs: 1000,
      dropPolicy: "drop_oldest_video",
      fps: 25,
      ...config,
    };
    this.onFrame = onFrame;
  }

  /** 入队一帧（从 Gateway 收到的 Avatar JPEG）。 */
  pushFrame(frame: AvatarFrame) {
    // Idle frame：音频仍在播（或说话帧队列非空）→ 排进同一队列沿时钟连播，
    // 避免句尾突然切静态画面；完全空闲 → 进 idleQueue 按 ~25fps 均匀直画。
    if (frame.tag === "idle") {
      const audioTime = this.config.getAudioTime?.() ?? 0;
      const audioStillPlaying =
        audioTime >= 0 && this.frameQueue.length > 0;
      if (audioStillPlaying) {
        this._enqueueSpeech(frame);
      } else {
        // 后台 tab 的 rAF 完全暂停、消费停摆——idle 帧只进不出会积压到
        // GB 级内存（speech 队列有 maxQueueSize 挡住，idle 队列此前裸奔）。
        // idle 旧帧无价值：后台直接丢弃；前台同款上限丢旧保新。
        if (typeof document !== "undefined" && document.hidden) return;
        if (this.idleQueue.length >= this.maxQueueSize) {
          this.idleQueue.shift();
        }
        this.idleQueue.push(frame);
        this._scheduleConsume();
      }
      return;
    }
    this._enqueueSpeech(frame);
  }

  private _enqueueSpeech(frame: AvatarFrame) {
    if (this.frameQueue.length >= this.maxQueueSize) {
      if (this.config.dropPolicy === "drop_oldest_video") {
        this.frameQueue.shift();
      } else if (this.config.dropPolicy === "drop_newest_video") {
        return; // 丢最新（不入队）
      } else {
        this.frameQueue.shift();
      }
    }
    this.frameQueue.push(frame);
    this._scheduleConsume();
  }

  /** 打断——清空队列并重置帧序号（此前只清队列不重置 idx：
      新回复 target 从 0 起算而 idx 已累积，帧永不消费、画面卡死）。 */
  interrupt() {
    this.frameQueue = [];
    this.idleQueue = [];
    this.videoFrameIdx = 0;
  }

  /** 新回复常规分支（VoxEMW needVideoBase 常规路径）：
      上段已播完——清帧队（去掉上段"闭嘴尾帧"）+ 帧序号归零。 */
  resetFrames() {
    this.frameQueue = [];
    this.videoFrameIdx = 0;
  }

  /** 连播分支（VoxEMW 注入式连续回复：垫场→正式）：
      绝不重锚清队——只裁剪上段回复的尾部零填充帧，保留未播真帧。
      prevEnd/responseAudioBase 为 PcmPlayer 绝对时钟（秒）。 */
  trimTailFrames(prevEnd: number, responseAudioBase: number) {
    const fps = this.config.fps ?? 25;
    const oldTotalFrames = Math.floor((prevEnd - responseAudioBase) * fps);
    const keep = Math.max(0, oldTotalFrames - this.videoFrameIdx);
    if (this.frameQueue.length > keep) {
      this.frameQueue.length = keep;
    }
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
    // 用 requestAnimationFrame 节流消费（~16ms，对齐 VoxEMW rAF 驱动）
    requestAnimationFrame(() => {
      this.consuming = false;
      this._consume();
    });
  }

  private _consume() {
    const audioTime = this.config.getAudioTime?.();
    const fps = this.config.fps ?? 25;
    const lag = this.config.videoLagFrames;

    // 0) idle 帧：完全空闲时按 ~25fps（40ms）节流直画
    if (this.idleQueue.length > 0 && this.frameQueue.length === 0) {
      const now = performance.now();
      if (now - this.lastIdleDrawAt >= 40) {
        const frame = this.idleQueue.shift()!;
        this.onFrame?.(frame);
        this.lastIdleDrawAt = now;
      }
    }

    // 1) 说话帧：按音频播放位置消费（音频主时钟驱动视频）
    if (audioTime !== undefined && this.frameQueue.length > 0) {
      const pos = audioTime;
      // 已播秒数 → 目标帧序号（25fps），减去口型滞后补偿
      const target = Math.floor(pos * fps) - lag;
      // 落后 >1s（fps 帧）跳帧追赶，绝不超前
      const maxAhead = fps;
      while (this.frameQueue.length > 0 && this.videoFrameIdx < target - maxAhead) {
        this.frameQueue.shift();
        this.videoFrameIdx++;
      }
      if (this.frameQueue.length > 0 && this.videoFrameIdx <= target) {
        const frame = this.frameQueue.shift()!;
        this.onFrame?.(frame);
        this.videoFrameIdx++;
      }
      return;
    }

    // 2) 无音频时钟：退化 rAF 按序消费（保持兼容）
    if (this.frameQueue.length > lag) {
      const frame = this.frameQueue.shift()!;
      this.onFrame?.(frame);
      this.videoFrameIdx++;
    }
  }
}
