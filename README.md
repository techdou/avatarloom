# AvatarLoom / 灵构

> Composable Digital Human Runtime
> 将声音、人格与形象，编织成可运行的数字人。

AvatarLoom 是一个模块化、积木式的实时 AI 数字人运行与管理平台。它把 VAD、STT、LLM、TTS、Avatar、Vision、Persona、Memory 等能力拆分为可替换 Block，由统一 Runtime Orchestrator 编排。

## 核心特性

- **积木式架构**：所有能力都是 Block，YAML 声明组合
- **实时语音对话**：VAD → STT → LLM → TTS → Avatar 完整链路
- **流式输出 + 打断**：LLM 流式 token、TTS 流式 PCM、用户随时打断
- **音画同步**：音频主时钟，Avatar 帧从属播放位置
- **Persona 切换**：人设/音色/形象/记忆同步切换
- **降级容错**：Avatar/Vision 失败不阻断语音链路
- **Mock 永远可跑**：不依赖 GPU/Docker/API Key
- **可观测**：每轮 Run 落盘事件流、性能指标、产物

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 20+
- pnpm 11+

### 安装

```bash
# Python 依赖（Mock 链路所需，不含 GPU 重依赖）
uv sync --extra dev

# Node 依赖
pnpm install

# 环境自检
uv run python scripts/doctor.py
```

### 运行 Mock 全链路

```bash
# 一键冒烟（不起服务，直接跑 Mock 链路）
uv run python scripts/smoke_mock.py

# 启动三服务
make dev
# 或
uv run python scripts/dev.py

# 浏览器打开
# http://127.0.0.1:3000 -> Realtime Playground
```

### 配置真实 Adapter（可选）

```bash
cp .env.example .env
# 编辑 .env 填 API Key（LLM/STT/TTS 任一）
```

填 OpenAI API Key 后，修改 profile 把对应 Block 改成 `*.openai-compatible`。

## 项目结构

```text
avatarloom/
├── apps/
│   ├── studio/              # Next.js 前端
│   ├── control-api/         # FastAPI REST（:8100）
│   └── runtime-gateway/     # FastAPI WebSocket（:8101）
├── packages/
│   ├── protocol/            # 事件 schema（Pydantic 单一来源）
│   └── sdk-python/          # Block SDK
├── runtime/
│   ├── orchestrator/        # 编排核心
│   ├── session/             # 状态机
│   ├── event_bus/           # 事件总线
│   ├── recorder/            # Run Recorder
│   └── ...
├── blocks/                  # 各类 Block 实现
│   ├── vad/{mock,silero}
│   ├── stt/{mock,sensevoice,openai_compatible}
│   ├── llm/{mock,openai_compatible,ollama}
│   ├── tts/{mock,openai_compatible,qwen3,voxcpm2}
│   ├── avatar/{mock,static,musetalk,flashhead}
│   └── vision/{mock,openai_compatible}
├── profiles/                # Runtime Profile（mock/lite-12gb/distributed/full-24gb）
├── personas/                # Persona 包
├── tests/                   # 单元/集成/E2E
├── scripts/                 # dev/doctor/smoke/gen_protocol
└── deploy/                  # Docker
```

## Runtime Profiles

| Profile | 说明 |
|---|---|
| `mock` | 纯 Mock，无 GPU/API Key，**默认推荐** |
| `lite-12gb` | 12GB GPU 单机（Silero + SenseVoice + Qwen3-TTS + MuseTalk） |
| `distributed` | 分布式（CPU STT + Remote LLM + Mac MLX TTS + NVIDIA Avatar） |
| `full-24gb` | 24GB+ GPU 全量（Silero + SenseVoice + VoxCPM2 + FlashHead） |

## 测试

```bash
make test              # Python + TypeScript 全量
make test-py           # 仅 Python
uv run pytest tests/   # 直接跑
make smoke             # Mock 冒烟
make doctor            # 环境自检
```

## Docker（可选）

```bash
docker compose -f deploy/docker-compose.yml up
```

三服务 + 数据卷 + healthcheck。Mock Profile 默认可用。

## 文档

- [架构](docs/architecture.md)
- [Block 开发指南](docs/block-development.md)
- [设计文档](docs/00-AvatarLoom-完整设计文档.md)
- [事件协议与状态机](docs/02-事件协议状态机与音画同步.md)
- [Studio 部署验收](docs/03-Studio部署安全与验收.md)

## 开发命令

```bash
make help      # 显示所有命令
make setup     # 安装依赖
make dev       # 启动开发环境
make test      # 全量测试
make lint      # ruff + ESLint
make type      # mypy + tsc
make fmt       # 格式化
make smoke     # Mock 冒烟
make doctor    # 环境自检
make docker    # Docker compose 校验
```

## 许可证

Apache-2.0
