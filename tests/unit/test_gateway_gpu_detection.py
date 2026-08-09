"""Gateway GPU 会话判定回归测试。"""

from __future__ import annotations

from avatarloom_runtime_gateway.ws_handler import _block_uses_gpu

from runtime.orchestrator.config import BlockRef


def test_explicit_gpu_deployment_is_detected() -> None:
    ref = BlockRef(id="avatar.remote", deployment="nvidia-cuda")

    assert _block_uses_gpu(ref) is True


def test_local_cuda_device_is_detected() -> None:
    ref = BlockRef(
        id="avatar.musetalk",
        deployment="local",
        config={"device": "cuda"},
    )

    assert _block_uses_gpu(ref) is True


def test_cuda_device_index_is_detected_case_insensitively() -> None:
    ref = BlockRef(
        id="tts.qwen3",
        deployment="local",
        config={"device": "CUDA:0"},
    )

    assert _block_uses_gpu(ref) is True


def test_cpu_and_mock_blocks_are_not_detected_as_gpu() -> None:
    assert (
        _block_uses_gpu(BlockRef(id="vad.silero", deployment="local", config={"device": "cpu"}))
        is False
    )
    assert _block_uses_gpu(BlockRef(id="vad.mock", deployment="mock")) is False
