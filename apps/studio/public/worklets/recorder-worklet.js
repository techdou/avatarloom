/**
 * AudioWorklet 处理器——麦克风采集 → 抗混叠降采样 → 16k PCM16 → port 发送。
 *
 * 重采样在音频线程完成（此前在主线程做简单平均抽取，无低通——48k 信号里
 * 8kHz 以上能量混叠折回语音带，SenseVoice 识别显著劣化）。
 * 方案：两级 RBJ biquad 低通（~4 阶 Butterworth，截止 7200Hz）+ 相位连续抽取。
 * worklet 内全局 sampleRate 即 context 采样率（44.1k/48k 均可）。
 *
 * 用法：
 *   await ctx.audioWorklet.addModule('/worklets/recorder-worklet.js');
 *   const node = new AudioWorkletNode(ctx, 'avatarloom-recorder');
 *   node.port.onmessage = (e) => { /* e.data 是 16k Int16Array *\/ };
 */

const TARGET_RATE = 16000;
const OUT_CHUNK = 1024; // 每凑够 1024 个 16k 样本（64ms）发送一次

/** RBJ cookbook 低通 biquad（归一化系数）。 */
function makeBiquad(fc) {
  const w0 = (2 * Math.PI * fc) / sampleRate;
  const alpha = Math.sin(w0) / (2 * 0.7071);
  const cw = Math.cos(w0);
  const a0 = 1 + alpha;
  return {
    x1: 0,
    x2: 0,
    y1: 0,
    y2: 0,
    b0: (1 - cw) / 2 / a0,
    b1: (1 - cw) / a0,
    b2: (1 - cw) / 2 / a0,
    a1: (-2 * cw) / a0,
    a2: (1 - alpha) / a0,
  };
}

class AvatarloomRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    // 两级级联低通 @7200Hz（Q=0.7071）——抽取前压掉奈奎斯特(8k)附近能量
    this._stages = [makeBiquad(7200), makeBiquad(7200)];
    // 抽取相位：浮点累计，保证跨 process() 块连续
    this._phase = 0;
    this._out = new Int16Array(OUT_CHUNK);
    this._outOffset = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;

    const ratio = sampleRate / TARGET_RATE;
    for (let i = 0; i < channel.length; i++) {
      let x = channel[i];
      // 级联滤波
      for (const f of this._stages) {
        const y = f.b0 * x + f.b1 * f.x1 + f.b2 * f.x2 - f.a1 * f.y1 - f.a2 * f.y2;
        f.x2 = f.x1;
        f.x1 = x;
        f.y2 = f.y1;
        f.y1 = y;
        x = y;
      }
      // 相位连续抽取：每 ratio 个滤波样本输出 1 个
      if (this._phase >= ratio - 1e-9) {
        this._phase -= ratio;
        const s = Math.max(-1, Math.min(1, x));
        this._out[this._outOffset++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this._outOffset >= OUT_CHUNK) {
          const chunk = new Int16Array(this._out);
          this.port.postMessage(chunk, [chunk.buffer]);
          this._outOffset = 0;
        }
      } else {
        this._phase += 1;
      }
    }
    return true;
  }
}

registerProcessor("avatarloom-recorder", AvatarloomRecorder);
