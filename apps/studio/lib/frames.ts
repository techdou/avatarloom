/**
 * 浏览器→Gateway 上行二进制帧构造（纯函数，可单测）。
 *
 * 协议（docs/02 协议章节 / gateway protocol.py）：
 * - 0x00 + PCM16：麦克风音频（显式 tag——裸 PCM 低字节可能自然等于 0x02 造成歧义）
 * - 0x02 + JPEG：摄像头截帧（Vision 多模态分析）
 * - 未知 tag 后端一律拒绝
 */

export const TAG_PCM_UPLINK = 0x00;
export const TAG_CAMERA_FRAME = 0x02;

/** 构造麦克风上行帧：0x00 + PCM16 原始字节。空输入返回 null（不发）。 */
export function buildPcmUplinkFrame(pcm: Int16Array): ArrayBuffer | null {
  if (pcm.byteLength === 0) return null;
  const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength);
  const frame = new Uint8Array(1 + bytes.length);
  frame[0] = TAG_PCM_UPLINK;
  frame.set(bytes, 1);
  return frame.buffer;
}

/** 构造摄像头截帧上行帧：0x02 + JPEG 字节。空输入返回 null（不发）。 */
export function buildCameraUplinkFrame(jpeg: Uint8Array): ArrayBuffer | null {
  if (jpeg.length === 0) return null;
  const frame = new Uint8Array(1 + jpeg.length);
  frame[0] = TAG_CAMERA_FRAME;
  frame.set(jpeg, 1);
  return frame.buffer;
}
