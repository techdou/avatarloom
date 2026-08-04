# avatarloom-sdk

AvatarLoom Block SDK — 开发新 Block 的 Python 基础库。

## 核心

- `Block`：单请求生命周期 Block（VAD/STT/Vision/Persona/Memory）
- `StreamingBlock`：流式 Block（LLM/TTS/Avatar）
- `BlockContext`：Block 运行时上下文（emit 事件、读配置、访问 logger）
- `BlockManifest`：Block 声明（标识、能力、I/O 事件、资源要求）

## 开发新 Block

```python
from avatarloom_sdk import Block, BlockContext, BlockManifest
from avatarloom_protocol import Event, AUDIO_APPENDED


class MyVadBlock(Block):
    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="vad.myimpl",
            name="My VAD",
            category="vad",
            inputs=[AUDIO_APPENDED],
            outputs=["speech.detected", "speech.ended"],
        )

    async def setup(self, ctx: BlockContext, config: dict) -> None: ...
    async def process(self, ctx: BlockContext, event: Event) -> None: ...
```
