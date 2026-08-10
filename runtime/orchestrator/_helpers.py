"""Orchestrator 内部共享常量和工具函数。

独立无依赖模块，orchestrator.py 和 coordinators.py 都从此导入，
避免 orchestrator <-> coordinators 循环导入（coordinators 需要这些常量，
orchestrator 创建 coordinator 实例时 coordinator 反向 import orchestrator）。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# 视觉触发词：用户说出这些词 → 下行 vision.request 让浏览器截帧分析
_VISION_TRIGGER_RE = re.compile(r"看看|评价|describe|looks?\s+like", re.IGNORECASE)

# 视觉上下文有效期（秒）：超过后不再注入 LLM
_VISION_CONTEXT_TTL_S = 30.0
# Vision 手动帧最小调用间隔（AL-P1-011 节流）——无同轮等待的帧限频
_VISION_MIN_INTERVAL_S = 2.0

# 单个 Block shutdown 的最长等待：GPU 模型释放/子进程终止正常秒级完成，
# 卡死（如子进程僵死、死锁）时跳过该 block 继续清理其余资源，不拖垮整体关停
_BLOCK_SHUTDOWN_TIMEOUT_S = 15.0

# Block category 标准名（和 Profile yaml 的 key 对齐）
CATEGORY_VAD = "vad"
CATEGORY_STT = "stt"
CATEGORY_LLM = "llm"
CATEGORY_TTS = "tts"
CATEGORY_AVATAR = "avatar"
CATEGORY_VISION = "vision"


def _read_wav_16k_mono_s16(path: Path) -> bytes | None:
    """读取 16kHz 单声道 s16 wav，返回裸 PCM；格式不符返回 None（VoxEMW 同款严格校验）。"""
    try:
        import wave

        with wave.open(str(path), "rb") as w:
            if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
                logger.warning("垫音格式不符（需 16k mono s16），跳过: %s", path)
                return None
            return w.readframes(w.getnframes())
    except Exception as e:
        logger.warning("垫音读取失败 %s: %s", path, e)
        return None
