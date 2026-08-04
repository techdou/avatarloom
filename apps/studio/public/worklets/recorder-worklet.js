/**
 * AudioWorklet 处理器——采集麦克风音频，转 PCM16 后通过 port 发送给主线程。
 *
 * 采样率：浏览器 AudioContext 默认 48000，我们需要 16000——在主线程做重采样。
 * 这里只做 float32 → int16 转换 + 缓冲发送。
 *
 * 用法：
 *   const ctx = new AudioContext();
 *   await ctx.audioWorklet.addModule('/worklets/recorder-worklet.js');
 *   const node = new AudioWorkletNode(ctx, 'avatarloom-recorder');
 *   node.port.onmessage = (e) => { /* e.data 是 Int16Array *\/ };
 */

const FRAME_SIZE = 4096; // 每次处理的采样数

class AvatarloomRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Int16Array(FRAME_SIZE);
    this._offset = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) {
      return true;
    }
    // 取第一个通道（单声道采集）
    const channel = input[0];
    if (!channel) return true;

    for (let i = 0; i < channel.length; i++) {
      // float32 [-1, 1] -> int16 [-32768, 32767]
      const s = Math.max(-1, Math.min(1, channel[i]));
      this._buffer[this._offset++] = s < 0 ? s * 0x8000 : s * 0x7fff;

      if (this._offset >= FRAME_SIZE) {
        // 拷贝一份发送（worklet 不能 transfer 原缓冲）
        const chunk = new Int16Array(this._buffer);
        this.port.postMessage(chunk, [chunk.buffer]);
        this._buffer = new Int16Array(FRAME_SIZE);
        this._offset = 0;
      }
    }
    return true;
  }
}

registerProcessor("avatarloom-recorder", AvatarloomRecorder);
