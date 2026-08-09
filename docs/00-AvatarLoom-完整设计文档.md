# AvatarLoom / 灵构——模块化实时数字人平台设计文档

版本：v0.1.0  
项目定位：Composable Digital Human Runtime  
默认仓库名：`avatarloom`  
许可证建议：Apache-2.0

> 更新：2026-08-09（全量 review 后同步）

## 1. 项目定义

AvatarLoom 是一个通过标准化积木模块搭建、编排、运行和管理实时 AI 数字人的开源平台。

系统将数字人的完整能力拆分为：

- VAD：语音活动检测。
- STT：语音转文字。
- LLM：对话推理。
- Memory：长期与短期记忆。
- Persona：人设和行为规则。
- TTS：文字转语音与音色克隆。
- Avatar：数字人形象与口型驱动。
- Vision：视觉感知。
- Skills：工具和业务能力。
- Transport：WebSocket、WebRTC、HTTP、RTMP。
- Safety：内容安全、授权和隐私。
- Observability：日志、指标、链路追踪和运行录制。

项目核心理念：

> 一个数字人不是一个模型，而是一组可以组合、替换、调度和观测的能力模块。

## 2. 项目目标

1. 支持实时语音数字人对话。
2. 支持单张图片或视频素材驱动口型。
3. 支持人设、音色和形象同步切换。
4. 支持本地模型、云 API 和混合部署。
5. 支持 12GB、24GB 和多机运行配置。
6. 通过 Studio 管理数字人、Block、Profile、Session 和 Run。
7. 通过 YAML 或 JSON 声明完整数字人。
8. 支持第三方开发新 Block。
9. 支持运行录制、回放、比较和分析。
10. 预留 MCP、Skills、知识库、工作流和多 Agent。

## 3. 总体架构

```text
AvatarLoom Studio
        │ REST / WebSocket
        ▼
Control Plane
        │ 创建 Session / Run
        ▼
Runtime Orchestrator
  ├── VAD
  ├── STT
  ├── Persona / Memory
  ├── LLM
  ├── TTS
  ├── Avatar
  ├── Vision / Skills
  └── Transport
        │
        ▼
Event Bus + Run Recorder + Artifact Store
```

### Studio

负责创建数字人、选择模块、配置 Persona、启动测试、查看日志、回放会话和分析性能。

### Control Plane

管理 Project、Avatar、Persona、BlockDefinition、BlockInstance、RuntimeProfile、SecretReference、Session、Run、Artifact 和 Evaluation。Control Plane 不直接执行 GPU 推理。

### Runtime Plane

负责 Session Manager、显式状态机、事件路由、中断、取消、超时、背压、降级、Audio Clock、Video Sync、Run Recorder 和 Artifact Writer。

### Model Plane

模型可以运行在同进程、独立进程、Docker、局域网服务、云 API、Mac MLX 或 NVIDIA CUDA。

## 4. 首版 Block

### VAD

- `vad.mock`
- `vad.silero`
- 预留 `vad.webrtc`

### STT

- `stt.mock`
- `stt.sensevoice`
- `stt.sensevoice-onnx`
- `stt.openai-compatible`
- 预留 `stt.qwen3-asr`

### LLM

- `llm.mock`
- `llm.openai-compatible`
- `llm.ollama`
- 预留 vLLM

Runtime 不得写死 DeepSeek、OpenAI 或其他提供商。

### TTS

- `tts.mock`
- `tts.openai-compatible`
- `tts.qwen3`（当前实现非真流式，整段合成后切片下发；manifest 已声明 `streaming=False`）
- 预留 `tts.cosyvoice`、`tts.voxcpm2`、`tts.mlx-remote`

### Avatar

- `avatar.mock`
- `avatar.static`
- `avatar.musetalk` 或 `avatar.livetalking`
- `avatar.flashhead`（已实现）

### Vision

- `vision.mock`
- `vision.openai-compatible`

Vision 未配置时不得阻断语音链路。

## 5. Persona Package

```text
personas/<id>/
├── persona.yaml
├── persona.md
├── voice/
│   ├── ref.wav
│   └── ref.txt
├── avatar/
│   ├── portrait.png
│   └── idle.mp4
├── knowledge/
└── fillers/
```

Persona 切换时同步更新：LLM Instructions、TTS Voice、Avatar Asset、Memory Namespace 和 Skill Permissions。

## 6. 推荐仓库结构

```text
avatarloom/
├── apps/
│   ├── studio/
│   ├── control-api/
│   └── runtime-gateway/
├── packages/
│   ├── protocol/
│   ├── config/
│   ├── sdk-python/
│   ├── sdk-typescript/
│   └── ui/
├── runtime/
│   ├── orchestrator/
│   ├── session/
│   ├── event_bus/
│   ├── sync/
│   ├── recorder/
│   ├── artifacts/
│   └── workers/
├── blocks/
│   ├── vad/
│   ├── stt/
│   ├── llm/
│   ├── persona/
│   ├── memory/
│   ├── tts/
│   ├── avatar/
│   ├── vision/
│   ├── skills/
│   └── transport/
├── personas/
├── profiles/
├── docs/
├── tests/
└── scripts/
```

## 7. 技术栈建议

Backend：Python 3.11+、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、asyncio、structlog、OpenTelemetry。

Frontend：Next.js、TypeScript、React、Tailwind CSS、shadcn/ui、React Flow、TanStack Query。

Testing：pytest、pytest-asyncio、Vitest、Playwright、ruff、mypy。

Deployment：Docker Compose、NVIDIA Container Toolkit、Nginx/Caddy、systemd/Supervisor。
