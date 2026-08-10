# avatarloom-sdk

AvatarLoom Block SDK — 开发新 Block 的 Python 基础库。

## 核心

- `Block`：Block 基类（VAD/STT/LLM/TTS/Avatar/Vision/Persona/Memory 均继承此类）
- `BlockContext`：Block 运行时上下文（emit 事件、读配置、访问 logger）
- `BlockManifest`：Block 声明（标识、能力、I/O 事件、资源要求）
- `AvatarState` / `transition_avatar_state`：avatar 门控状态推导纯函数

流式 Block（LLM/TTS/Avatar）同样继承 `Block`，通过 `process(event)` 逐个处理
流式事件实现流式语义，不需要单独的基类。

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

    async def setup(self, ctx: BlockContext) -> None: ...
    async def process(self, ctx: BlockContext, event: Event) -> None: ...
```
