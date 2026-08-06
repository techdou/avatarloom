/**
 * 麦克风音频采集器。
 *
 * 用 AudioWorklet 采集 → 48kHz float32 → 转 16kHz int16 PCM → 通过回调发送。
 *
 * 重采样策略：浏览器 AudioContext 通常是 44100/48000，我们需要 16000。
 * 用简单的线性降采样（每 N 个样本取 1 个）。生产可换 OfflineAudioContext 高质量重采样。
 */

export interface RecorderOptions {
  /** 目标采样率，默认 16000 */
  targetSampleRate?: number;
  /** PCM chunk 回调（Int16Array） */
  onChunk: (pcm: Int16Array) => void;
  /** 错误回调 */
  onError?: (e: Error) => void;
}

export class MicrophoneRecorder {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private analyser: AnalyserNode | null = null;
  private levelBuf: Uint8Array | null = null;
  private targetRate: number;
  private onChunk: (pcm: Int16Array) => void;
  private onError?: (e: Error) => void;
  private _active = false;

  constructor(opts: RecorderOptions) {
    this.targetRate = opts.targetSampleRate ?? 16000;
    this.onChunk = opts.onChunk;
    this.onError = opts.onError;
  }

  get isActive() {
    return this._active;
  }

  async start() {
    if (this._active) return;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      // 用原始采样率创建 context（避免双重重采样）
      const track = this.stream.getAudioTracks()[0];
      const settings = track.getSettings();
      const sourceRate = settings.sampleRate ?? 48000;

      this.ctx = new AudioContext({ sampleRate: sourceRate });
      await this.ctx.audioWorklet.addModule("/worklets/recorder-worklet.js");

      this.source = this.ctx.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.ctx, "avatarloom-recorder");

      // 音量采样支路（UI 波形指示用，不影响 PCM 链路）
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 256;
      this.source.connect(this.analyser);

      // worklet 输出原始采样率的 PCM16，主线程重采样到 targetRate
      const ratio = sourceRate / this.targetRate;
      let resampleBuffer: number[] = [];

      this.node.port.onmessage = (e: MessageEvent) => {
        const pcm: Int16Array = e.data;
        // 线性降采样
        for (let i = 0; i < pcm.length; i++) {
          resampleBuffer.push(pcm[i]);
        }
        // 每凑够 ratio 个样本输出 1 个
        const out = new Int16Array(Math.floor(resampleBuffer.length / ratio));
        let outIdx = 0;
        let bufIdx = 0;
        while (bufIdx + ratio <= resampleBuffer.length) {
          // 简单平均
          let sum = 0;
          const baseIdx = Math.floor(bufIdx);
          for (let j = 0; j < Math.ceil(ratio); j++) {
            sum += resampleBuffer[baseIdx + j] ?? 0;
          }
          out[outIdx++] = Math.round(sum / Math.ceil(ratio));
          bufIdx += ratio;
        }
        // 保留余数
        resampleBuffer = resampleBuffer.slice(Math.floor(bufIdx));
        if (out.length > 0) {
          this.onChunk(out);
        }
      };

      this.source.connect(this.node);
      // worklet 不连 destination（避免回环）
      this._active = true;
    } catch (e) {
      this.onError?.(e instanceof Error ? e : new Error(String(e)));
      this.stop();
    }
  }

  /** 当前麦克风音量（0-1，RMS 压缩映射）。未激活时返回 0。UI 波形轮询用。 */
  getLevel(): number {
    if (!this.analyser || !this._active) return 0;
    if (!this.levelBuf || this.levelBuf.length !== this.analyser.fftSize) {
      this.levelBuf = new Uint8Array(this.analyser.fftSize);
    }
    this.analyser.getByteTimeDomainData(this.levelBuf);
    let sum = 0;
    for (let i = 0; i < this.levelBuf.length; i++) {
      const v = (this.levelBuf[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / this.levelBuf.length);
    // 语音 RMS 典型 0.02-0.3，放大并截断到 0-1
    return Math.min(1, rms * 3.5);
  }

  stop() {
    this._active = false;
    if (this.node) {
      this.node.port.close();
      this.node.disconnect();
      this.node = null;
    }
    if (this.analyser) {
      this.analyser.disconnect();
      this.analyser = null;
    }
    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }
    if (this.ctx) {
      this.ctx.close();
      this.ctx = null;
    }
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
  }
}
