# AvatarLoom 架构

## 总体架构

```text
浏览器
  │ WebSocket /ws/realtime（JSON 控制 + 二进制 PCM/JPEG）
  ▼
Runtime Gateway（apps/runtime-gateway，:8101）
  │ 装配 Orchestrator + Session + EventBus
  ▼
Orchestrator（runtime/orchestrator）
  ├── VAD Block → speech.detected/ended
  ├── STT Block → transcript.completed
  ├── LLM Block → llm.text.delta/done（流式）
  ├── TTS Block → tts.audio.delta/completed（流式 PCM）
  ├── Avatar Block → avatar.speech_frame/idle_frame（JPEG）
  └── Vision Block（可选）→ vision.result
        │
        ▼
EventBus + RunRecorder + ArtifactWriter
  │
  ▼
Control API（apps/control-api，:8100，REST）
  ├── Project / Avatar / Persona / BlockDefinition
  ├── RuntimeProfile / SecretReference
  └── Session / Run / Artifact（只读）
```

## 三服务分离

| 服务 | 端口 | 职责 |
|---|---|---|
| Control API | 8100 | REST CRUD，管理元数据（Project/Persona/Block/Profile/Session/Run） |
| Runtime Gateway | 8101 | WebSocket 实时通道，装配 Orchestrator，音频双向流 |
| Studio | 3000 | Next.js 前端，调用 Control API + 连 Runtime Gateway |

浏览器**只连 Runtime Gateway**——Control API 的数据通过 Gateway 代理或 Studio 服务端调用。

## 核心抽象

### Block

所有能力（VAD/STT/LLM/TTS/Avatar/Vision/Persona/Memory）都是 Block。
Block 通过 manifest 声明能力，通过 EventBus 订阅/发布事件。

```python
class Block(abc.ABC):
    async def setup(self, ctx: BlockContext) -> None: ...
    async def process(self, ctx: BlockContext, event: Event) -> None: ...
    async def reset(self, session_id: str) -> None: ...
    async def health(self) -> HealthStatus: ...
    async def shutdown(self) -> None: ...
```

### 状态机

显式状态机驱动会话：

```text
IDLE → LISTENING → TRANSCRIBING → THINKING → SPEAKING → IDLE
                       ↑              ↓            ↓
                     INTERRUPTING ←────────────── 用户打断
```

非法转换 raise `IllegalTransitionError`——不用散落布尔变量。

### 音频主时钟

- 音频用 AudioContext.currentTime 精确调度
- Avatar 帧从属音频播放位置
- 视频落后允许跳帧（drop_oldest）
- 打断时清空音频 + 帧队列

## 降级策略

- Avatar Block 失败 → fallback 到 `avatar.static` 或 `avatar.mock`
- Vision Block 失败（optional）→ 直接缺席，不阻断语音链路
- GPU Block import 失败 → Orchestrator 跳过或降级
- Mock Profile 始终可运行——不依赖 GPU/Docker/API Key

## 协议

事件用统一 Envelope（见 `packages/protocol`）：

```json
{
  "id": "evt_xxx",
  "type": "transcript.completed",
  "session_id": "ses_xxx",
  "run_id": "run_xxx",
  "timestamp": 0,
  "source": "stt.mock",
  "sequence": 1,
  "payload": {}
}
```

Pydantic 为单一来源，TypeScript 类型从 JSON Schema 自动生成（`scripts/gen_protocol.py`）。
