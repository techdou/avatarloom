/**
 * PCM16 音频播放器——AudioContext 时钟调度。
 *
 * 设计（参考 VoxEMW assistant.js 的播放方案）：
 * - 收到的 PCM16 chunk 按顺序转 AudioBuffer
 * - 用 AudioContext.currentTime 精确调度，无缝拼接
 * - 支持打断清空队列
 * - 支持 audioDelayMs（对齐 Avatar 视频固有延迟）
 *
 * 不用 MediaSource（碎片 PCM 不友好），不用顺序 await（时钟会漂）。
 */

export interface PlayerOptions {
  sampleRate?: number;
  /** 音频基础延迟（毫秒），用于对齐视频生成延迟。默认 0 */
  audioDelayMs?: number;
}

export class PcmPlayer {
  private ctx: AudioContext | null = null;
  private sampleRate: number;
  private audioDelayMs: number;
  /** 下一个 chunk 的播放起始时间（AudioContext 时钟） */
  private nextStartTime = 0;
  /** 已调度的 source 节点（用于打断时停止） */
  private scheduledSources: AudioBufferSourceNode[] = [];
  /** 本回复首个 chunk 的起始播放时间（AudioContext 时钟），用于计算 currentTime */
  private responseAudioBase = 0;

  /**
   * 当前音频播放位置（秒，相对本回复起点）。
   * 负值 = 首个 chunk 还没到播放时间（调度中）。
   * 用于驱动视频帧消费（对齐 VoxEMW assistant.js 的音频主时钟模型）。
   */
  get currentTime() {
    if (!this.ctx) return 0;
    return this.ctx.currentTime - this.responseAudioBase;
  }

  constructor(opts: PlayerOptions = {}) {
    this.sampleRate = opts.sampleRate ?? 16000;
    this.audioDelayMs = opts.audioDelayMs ?? 0;
  }

  private ensureCtx() {
    if (!this.ctx) {
      this.ctx = new AudioContext({ sampleRate: this.sampleRate });
      this.nextStartTime = this.ctx.currentTime + this.audioDelayMs / 1000;
    }
    return this.ctx;
  }

  /** 在用户手势内调用，解锁被浏览器自动暂停的 AudioContext。 */
  async resume() {
    const ctx = this.ensureCtx();
    if (ctx.state === "suspended") {
      try {
        await ctx.resume();
      } catch {
        /* 忽略——下次 enqueue 时再试 */
      }
    }
    return ctx;
  }

  /** 喂入一个 PCM16 chunk。立即调度播放。 */
  enqueue(pcm: Int16Array) {
    const ctx = this.ensureCtx();
    // 如果上次调度的结束时间已过，从当前时间 + delay 开始（避免追赶堆积）
    const now = ctx.currentTime;
    if (this.nextStartTime < now + this.audioDelayMs / 1000) {
      this.nextStartTime = now + this.audioDelayMs / 1000;
    }
    // 首个 chunk：锚定本回复的音频时间轴起点（VoxEMW responseAudioBase）
    if (this.scheduledSources.length === 0) {
      this.responseAudioBase = this.nextStartTime;
    }

    const buf = ctx.createBuffer(1, pcm.length, this.sampleRate);
    const channel = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) {
      channel[i] = pcm[i] / 32768;
    }

    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    src.start(this.nextStartTime);

    this.scheduledSources.push(src);
    this.nextStartTime += buf.duration;

    // 清理已播完的 source
    src.onended = () => {
      this.scheduledSources = this.scheduledSources.filter((s) => s !== src);
    };
  }

  /** 打断——立即停止所有播放，清空队列。 */
  interrupt() {
    for (const src of this.scheduledSources) {
      try {
        src.stop();
      } catch {
        // 已经停了
      }
    }
    this.scheduledSources = [];
    if (this.ctx) {
      this.nextStartTime = this.ctx.currentTime + this.audioDelayMs / 1000;
      this.responseAudioBase = this.nextStartTime;
    }
  }

  /** 是否正在播放。 */
  get isPlaying() {
    return this.scheduledSources.length > 0;
  }

  /** 重置（新会话）。 */
  reset() {
    this.interrupt();
    this.nextStartTime = 0;
  }

  /** 释放资源。 */
  close() {
    this.interrupt();
    if (this.ctx) {
      this.ctx.close();
      this.ctx = null;
    }
  }
}
