# 开发新 Block

## 快速开始

### 1. 写 Block 类

```python
# blocks/vad/myimpl.py
from avatarloom_protocol import AUDIO_APPENDED, Event, SPEECH_DETECTED, SPEECH_ENDED
from avatarloom_sdk import Block, BlockContext, BlockManifest, Capability, ResourceRequirements


class MyVadBlock(Block):
    @classmethod
    def manifest(cls) -> BlockManifest:
        return BlockManifest(
            block_id="vad.myimpl",
            name="My VAD",
            category="vad",
            inputs=[AUDIO_APPENDED],
            outputs=[SPEECH_DETECTED, SPEECH_ENDED],
            resources=ResourceRequirements(accelerator=["cpu"]),
            config_schema={
                "type": "object",
                "properties": {
                    "threshold": {"type": "number", "default": 0.5},
                },
            },
        )

    async def setup(self, ctx: BlockContext) -> None:
        self._threshold = float(ctx.config.get("threshold", 0.5))
        self._mark_ready()

    async def process(self, ctx: BlockContext, event: Event) -> None:
        if event.type != AUDIO_APPENDED:
            return
        # 处理音频...
        await ctx.emit(Event(
            type=SPEECH_DETECTED,
            session_id=ctx.session_id,
            source="vad.myimpl",
            run_id=ctx.run_id,
            payload={"confidence": 0.9},
        ))

    async def reset(self, session_id: str) -> None:
        """用户打断时清状态。"""
        pass
```

### 2. 注册到 Orchestrator

```python
# runtime/orchestrator/orchestrator.py 的 BLOCK_REGISTRY
BLOCK_REGISTRY["vad.myimpl"] = "blocks.vad.myimpl:MyVadBlock"
```

或运行时动态注册：

```python
from runtime.orchestrator.orchestrator import register_block
register_block("vad.myimpl", "blocks.vad.myimpl:MyVadBlock")
```

### 3. 在 Profile 中引用

```yaml
# profiles/my.yaml
blocks:
  vad:
    id: vad.myimpl
    deployment: local
    config:
      threshold: 0.3
```

### 4. 写测试

参考 `tests/unit/test_mock_blocks.py`——测试 setup/process/reset/health。

## Block 生命周期

```text
setup(ctx) → warmup() → [process(ctx, event) × N] → reset(session_id) × M → shutdown()
```

- `setup`：加载模型/建立连接（失败 raise BlockSetupError）
- `warmup`：预热（torch.compile 等，可选）
- `process`：处理事件，可能 emit 新事件（必须支持 asyncio 取消）
- `reset`：用户打断时清状态（可选）
- `health`：返回健康状态（默认 healthy）
- `shutdown`：释放资源（可选）

## 流式 Block

LLM/TTS/Avatar 用 `StreamingBlock`：

```python
class MyTtsBlock(StreamingBlock):
    async def open_stream(self, ctx: BlockContext) -> None: ...
    async def push(self, ctx: BlockContext, chunk: Any) -> None: ...
    async def flush(self) -> None: ...
    async def close_stream(self) -> None: ...
```

## 重型依赖隔离

GPU/大型库依赖用 `[project.optional-dependencies]` 的 extras：

```toml
[project.optional-dependencies]
myimpl = ["torch>=2.2"]
```

Block 在 setup 时惰性 import：

```python
async def setup(self, ctx: BlockContext) -> None:
    try:
        import torch
    except ImportError as e:
        raise BlockSetupError(
            self.manifest().block_id,
            f"依赖未安装: {e}. 运行 uv sync --extra myimpl",
        ) from e
```

Orchestrator 会捕获 BlockSetupError 并降级到 fallback 或跳过 optional Block。

## 事件协议

所有事件用 `avatarloom_protocol.Event`：

```python
from avatarloom_protocol import Event, LLM_TEXT_DELTA

await ctx.emit(Event(
    type=LLM_TEXT_DELTA,
    session_id=ctx.session_id,
    source="llm.myblock",
    run_id=ctx.run_id,
    payload={"text": "你好"},
))
```

自定义事件类型用字符串——Block 的 manifest.inputs/outputs 声明订阅/产出的事件类型。
