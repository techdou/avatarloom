"""avtr1 block 协议层单测（无 GPU / 无真实 worker 子进程）。

用 asyncio.StreamReader 手工填充字节流模拟 worker stdout：
- 控制应答按 id 配对（_call_worker）
- 帧包入 _frame_queue（背压解耦后不再内联 emit）
- EOF（worker 死亡）→ fail 所有 pending + _ready 复位（崩溃不静默）
"""

from __future__ import annotations

import asyncio
import json
import struct
import types as py_types

from blocks.avatar.avtr1 import (
    FRAME_QUEUE_MAX,
    PKT_CONTROL,
    PKT_FRAME,
    Avtr1AvatarBlock,
)


class _WriterStub:
    """_send 只用 write/drain——记录写入供断言。"""

    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None


def _make_block() -> tuple[Avtr1AvatarBlock, asyncio.StreamReader, _WriterStub]:
    block = Avtr1AvatarBlock()
    reader = asyncio.StreamReader()
    writer = _WriterStub()
    block._worker_proc = py_types.SimpleNamespace(returncode=None, stdout=reader)
    block._worker_stdin = writer
    return block, reader, writer


def _packet(pkt_type: int, payload: bytes) -> bytes:
    return bytes([pkt_type]) + struct.pack(">I", len(payload)) + payload


class TestCallWorker:
    async def test_response_paired_by_id(self) -> None:
        block, reader, _ = _make_block()
        task = asyncio.create_task(block._read_packets())
        # 先发 call（rid=1 登记）再喂应答——预填应答会在 rid 登记前被 reader 丢弃
        call = asyncio.create_task(block._call_worker({"cmd": "ping"}, timeout=2.0))
        await asyncio.sleep(0.05)
        reader.feed_data(
            _packet(PKT_CONTROL, json.dumps({"id": 1, "ok": True, "type": "pong"}).encode())
        )
        resp = await asyncio.wait_for(call, 2.0)
        assert resp["ok"] is True
        reader.feed_eof()
        await asyncio.wait_for(task, 2.0)

    async def test_worker_error_raises(self) -> None:
        block, reader, _ = _make_block()
        task = asyncio.create_task(block._read_packets())
        call = asyncio.create_task(block._call_worker({"cmd": "ping"}, timeout=2.0))
        await asyncio.sleep(0.05)  # 让 _send 完成、rid=1 已登记
        reader.feed_data(
            _packet(PKT_CONTROL, json.dumps({"id": 1, "ok": False, "error": "boom"}).encode())
        )
        try:
            await asyncio.wait_for(call, 2.0)
            raise AssertionError("should raise")
        except RuntimeError as e:
            assert "boom" in str(e)
        reader.feed_eof()
        await asyncio.wait_for(task, 2.0)

    async def test_eof_fails_pending_immediately(self) -> None:
        # 崩溃不静默：worker 死亡（stdout EOF）时挂起中的 _call_worker 立即失败，
        # 而非干等满 timeout（setup ping 600s 卡死场景的回归锚）
        block, reader, _ = _make_block()
        task = asyncio.create_task(block._read_packets())
        call = asyncio.create_task(block._call_worker({"cmd": "ping"}, timeout=60.0))
        await asyncio.sleep(0.05)
        assert not call.done()
        t0 = asyncio.get_running_loop().time()
        reader.feed_eof()
        try:
            await asyncio.wait_for(call, 2.0)
            raise AssertionError("should raise")
        except RuntimeError as e:
            assert "worker exited" in str(e)
        # 立即失败——远小于 60s timeout
        assert asyncio.get_running_loop().time() - t0 < 1.5
        await asyncio.wait_for(task, 2.0)
        # worker 死亡后状态复位：后续命令被 None 守卫拦截
        assert block._worker_stdin is None
        assert block._ready is False


class TestFrameQueue:
    async def test_frame_enqueued_not_inline_emitted(self) -> None:
        # 背压解耦：reader 只入队，不内联 emit（慢客户端不拖死控制通道）
        block, reader, _ = _make_block()
        task = asyncio.create_task(block._read_packets())
        reader.feed_data(_packet(PKT_FRAME, b"\x01" + b"jpegbytes"))
        for _ in range(100):
            if block._frame_queue.qsize() == 1:
                break
            await asyncio.sleep(0.01)
        assert block._frame_queue.qsize() == 1
        jpeg, is_speech = block._frame_queue.get_nowait()
        assert jpeg == b"jpegbytes"
        assert is_speech is True
        reader.feed_eof()
        await asyncio.wait_for(task, 2.0)

    async def test_frame_queue_drops_oldest_when_full(self) -> None:
        block, reader, _ = _make_block()
        task = asyncio.create_task(block._read_packets())
        for i in range(FRAME_QUEUE_MAX + 5):
            reader.feed_data(_packet(PKT_FRAME, b"\x00" + str(i).encode()))
        for _ in range(200):
            if block._frame_queue.qsize() == FRAME_QUEUE_MAX:
                break
            await asyncio.sleep(0.01)
        # 队满丢最旧：最早的 0-4 被丢，队头是 5
        jpeg, _ = block._frame_queue.get_nowait()
        assert jpeg == b"5"
        reader.feed_eof()
        await asyncio.wait_for(task, 2.0)


class TestSessionLifecycle:
    async def test_on_session_end_clears_ctx(self) -> None:
        block = Avtr1AvatarBlock()
        block._ctxs["s1"] = object()  # type: ignore[assignment]
        block._speaking["s1"] = True
        block._frame_indexes["s1"] = 42
        await block.on_session_end("s1")
        assert "s1" not in block._ctxs
        assert "s1" not in block._speaking
        assert "s1" not in block._frame_indexes
