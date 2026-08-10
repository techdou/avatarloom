"""Block 注册表——Block ID → entrypoint 映射。

独立模块，纯数据无依赖。orchestrator 和 profile_loader 都从此导入，
避免配置层反向依赖 runtime 核心。
"""

from __future__ import annotations

# Block ID -> entrypoint 映射。v0.1 用 Mock 全部注册。
# 真实 Adapter 在阶段 5/6/8 增补。
BLOCK_REGISTRY: dict[str, str] = {
    "vad.mock": "blocks.vad.mock:MockVadBlock",
    "stt.mock": "blocks.stt.mock:MockSttBlock",
    "llm.mock": "blocks.llm.mock:MockLlmBlock",
    "tts.mock": "blocks.tts.mock:MockTtsBlock",
    "avatar.mock": "blocks.avatar.mock:MockAvatarBlock",
    "vision.mock": "blocks.vision.mock:MockVisionBlock",
    # 真实 Adapter（阶段 5+ 实装，这里先注册 entrypoint）
    "vad.silero": "blocks.vad.silero:SileroVadBlock",
    "stt.sensevoice": "blocks.stt.sensevoice:SenseVoiceSttBlock",
    "stt.openai-compatible": "blocks.stt.openai_compatible:OpenAISttBlock",
    "llm.openai-compatible": "blocks.llm.openai_compatible:OpenAILlmBlock",
    "llm.ollama": "blocks.llm.ollama:OllamaLlmBlock",
    "tts.openai-compatible": "blocks.tts.openai_compatible:OpenAITtsBlock",
    "tts.qwen3": "blocks.tts.qwen3:Qwen3TtsBlock",
    "tts.voxcpm2": "blocks.tts.voxcpm2:VoxCpm2TtsBlock",
    "avatar.static": "blocks.avatar.static:StaticAvatarBlock",
    "avatar.musetalk": "blocks.avatar.musetalk:MuseTalkAvatarBlock",
    "avatar.flashhead": "blocks.avatar.flashhead:FlashHeadAvatarBlock",
    "vision.openai-compatible": "blocks.vision.openai_compatible:OpenAIVisionBlock",
    "memory.mem0-local": "blocks.memory.mem0_local:Mem0MemoryBlock",
}


def register_block(block_id: str, entrypoint: str) -> None:
    """第三方注册新 Block。"""
    BLOCK_REGISTRY[block_id] = entrypoint
