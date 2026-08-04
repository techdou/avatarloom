# avatarloom-protocol

AvatarLoom 事件协议包——所有跨服务、跨 Block、前后端共享的事件 schema 的**单一来源**。

## 设计原则

1. **Pydantic v2 模型为单一来源**：Python 服务直接 import 使用。
2. **JSON Schema 自动导出**：供 TypeScript 客户端、Control API 校验、Block Manifest 引用。
3. **TypeScript 类型自动生成**：`scripts/gen_protocol.py` 从 JSON Schema 生成 `.ts` 类型到 `packages/sdk-typescript/src/generated/`。
4. **向后兼容**：事件字段只能新增，不能删除或改名；新增字段必须有默认值。

## 事件分类

| 前缀 | 说明 |
|---|---|
| `session.*` | 会话生命周期 |
| `audio.*` | 原始音频上下行（PCM chunk） |
| `speech.*` | VAD 检测结果 |
| `transcript.*` | STT 识别结果 |
| `llm.*` | LLM 推理（text delta、done） |
| `tts.*` | TTS 合成（audio delta、completed） |
| `avatar.*` | 数字人帧（speech frame、idle frame） |
| `vision.*` | 视觉感知 |
| `persona.*` | 人设切换 |
| `response.*` | 整轮回复生命周期（started/done/interrupted） |
| `block.*` | Block 生命周期（setup/ready/error/health） |
| `run.*` | Run 记录（started/metrics/completed） |
| `artifact.*` | Artifact 产出 |

## 使用

```python
from avatarloom_protocol import Event, EventType, SessionStarted
```
