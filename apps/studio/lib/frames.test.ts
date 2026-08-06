import { describe, it, expect } from "vitest";
import {
  TAG_PCM_UPLINK,
  TAG_CAMERA_FRAME,
  buildPcmUplinkFrame,
  buildCameraUplinkFrame,
} from "./frames";

describe("上行二进制帧构造", () => {
  it("PCM 帧：0x00 tag + 原样 PCM 字节", () => {
    const pcm = new Int16Array([0x0201, -100, 32000, 0x02ff]); // 首样本低字节即 0x01/0xff 混淆场景
    const frame = buildPcmUplinkFrame(pcm);
    expect(frame).not.toBeNull();
    const view = new Uint8Array(frame!);
    expect(view[0]).toBe(TAG_PCM_UPLINK);
    expect(view.length).toBe(1 + pcm.byteLength);
    // payload 与原 PCM 逐字节一致（后端按 0x00 显式路由，不再误判 0x02）
    expect(Array.from(view.slice(1))).toEqual(
      Array.from(new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength))
    );
  });

  it("PCM 低字节为 0x02 时仍走 0x00 通道（AL-P1-001 核心场景）", () => {
    // 16-bit 样本 0x0002 的字节序：02 00——裸发送时首字节 0x02 会被后端误判为摄像头帧
    const pcm = new Int16Array([0x0002, 0x0302]);
    const frame = buildPcmUplinkFrame(pcm)!;
    const view = new Uint8Array(frame);
    expect(view[0]).toBe(TAG_PCM_UPLINK); // 显式 tag 盖过载荷首字节
    expect(view[1]).toBe(0x02); // 载荷原样保留
  });

  it("空 PCM 返回 null", () => {
    expect(buildPcmUplinkFrame(new Int16Array(0))).toBeNull();
  });

  it("摄像头帧：0x02 tag + JPEG 字节", () => {
    const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]); // JPEG SOI 头
    const frame = buildCameraUplinkFrame(jpeg)!;
    const view = new Uint8Array(frame);
    expect(view[0]).toBe(TAG_CAMERA_FRAME);
    expect(view.length).toBe(1 + jpeg.length);
    expect(Array.from(view.slice(1))).toEqual(Array.from(jpeg));
  });

  it("空 JPEG 返回 null", () => {
    expect(buildCameraUplinkFrame(new Uint8Array(0))).toBeNull();
  });

  it("Int16Array 带 byteOffset（ subarray 视图）时只打包可见区间", () => {
    const backing = new Int16Array([111, 222, 333, 444]);
    const view16 = backing.subarray(1, 3); // [222, 333]
    const frame = buildPcmUplinkFrame(view16)!;
    const view = new Uint8Array(frame);
    expect(Array.from(view.slice(1))).toEqual(
      Array.from(new Uint8Array(view16.buffer, view16.byteOffset, view16.byteLength))
    );
  });
});
