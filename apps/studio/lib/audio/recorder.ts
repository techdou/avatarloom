/**
 * 麦克风音频采集器。
 *
 * AudioWorklet 采集（context 用麦克风原生采样率，避免双重重采样）→
 * worklet 内抗混叠低通 + 降采样到 16k PCM16（见 public/worklets/recorder-worklet.js）
 * → 回调发送。
 */

export interface RecorderOptions {
  /** PCM chunk 回调（16k Int16Array） */
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
  private onChunk: (pcm: Int16Array) => void;
  private onError?: (e: Error) => void;
  private _active = false;
  // start/stop 竞态标记：stop() 置位后，pending 的 getUserMedia 回调检查此标记，
  // 若已取消则停 track 直接退出——否则 stream/node/ctx 全部赋值但实例已无引用，
  // 麦克风硬件常开、指示灯常亮（隐私敏感泄漏）
  private _cancelled = false;

  constructor(opts: RecorderOptions) {
    this.onChunk = opts.onChunk;
    this.onError = opts.onError;
  }

  get isActive() {
    return this._active;
  }

  async start() {
    if (this._active) return;
    this._cancelled = false;
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      // 竞态检查：getUserMedia 授权弹窗可能挂起数秒，期间 hook 可能已 disconnect→stop
      if (this._cancelled) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      this.stream = stream;
      // 用原始采样率创建 context（避免双重重采样）
      const track = this.stream.getAudioTracks()[0];
      const settings = track.getSettings();
      const sourceRate = settings.sampleRate ?? 48000;

      this.ctx = new AudioContext({ sampleRate: sourceRate });
      await this.ctx.audioWorklet.addModule("/worklets/recorder-worklet.js");

      // 竞态检查：addModule 期间也可能被 stop
      if (this._cancelled) {
        this.stop();
        return;
      }

      this.source = this.ctx.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.ctx, "avatarloom-recorder");

      // 音量采样支路（UI 波形指示用，不影响 PCM 链路）
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 256;
      this.source.connect(this.analyser);

      // worklet 已在音频线程完成抗混叠低通 + 降采样到 16k PCM16
      // （此前主线程简单平均抽取无低通，高频混叠折回语音带，STT 识别劣化）
      this.node.port.onmessage = (e: MessageEvent) => {
        const pcm: Int16Array = e.data;
        if (pcm.length > 0) {
          this.onChunk(pcm);
        }
      };

      this.source.connect(this.node);
      // worklet 不连 destination（避免回环）
      this._active = true;
    } catch (e) {
      this.onError?.(e instanceof Error ? e : new Error(String(e)));
      this.stop();
      // rethrow——hook 侧据此决定是否 setMicActive(true)。
      // 此前 catch 吞错不 rethrow，授权被拒后 UI 仍显示"录音中"，说了白说。
      throw e instanceof Error ? e : new Error(String(e));
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
    this._cancelled = true;
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
