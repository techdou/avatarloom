# AvatarLoom / 灵构

> Composable Digital Human Runtime
> 将声音、人格、形象与记忆，编织成可运行的数字人。

AvatarLoom 是一个模块化、积木式的实时 AI 数字人运行与管理平台。它把 VAD、STT、LLM、TTS、Avatar、Vision、Memory、Persona 等能力拆分为可替换 Block，由统一 Runtime Orchestrator 通过事件总线编排。

## 核心特性

- **积木式架构**：所有能力都是 Block，YAML 声明式组合，换组件不改代码
- **实时语音对话**：VAD → STT → LLM → TTS → Avatar 完整流式链路
- **流式输出 + 打断**：LLM 流式 token、TTS 流式 PCM，用户随时打断且任务真取消
- **音画同步**：音频主时钟，Avatar 帧从属播放位置；连播回复画面不冻结
- **视觉感知**：触发词命中 → 截帧 → 多模态分析 → 同轮注入回答
- **长期记忆**：Mem0 内嵌记忆（本地向量库，可选启用，默认关闭）
- **Persona 一体**：人设/音色/形象/垫音/记忆按包切换
- **降级容错**：Block 失败按 fallback 链降级并显式记录，不静默
- **Mock 永远可跑**：不依赖 GPU/Docker/API Key 的完整开发回归链路
- **可观测**：每轮 Run 落盘事件流、首字/首音/首帧延迟、降级路径与产物

## 端口约定（唯一权威）

AvatarLoom 的端口分两层，**用户访问永远走"访问入口"一列，不直连服务端口**：

| 服务 | 服务端口（进程监听） | 本地 dev 直连 | **AutoDL 隧道访问入口（统一）** |
|---|---|---|---|
| Studio | 3000 | `http://127.0.0.1:3000` | **`http://localhost:13000`** |
| Control API | 8100 | `http://127.0.0.1:8100` | **`http://localhost:18100`** |
| Runtime Gateway | 8101 | `ws://127.0.0.1:8101/ws/realtime` | **`ws://localhost:18101/ws/realtime`** |

- **AutoDL 场景**：SSH 隧道把服务器 3000/8100/8101 映射到本地 13000/18100/18101。
  浏览器地址栏、WS 目标、演示链接、文档示例**只允许出现隧道端口**。
  前端 WS 地址自动推导（页面端口 >10000 时按隧道映射换算），无需 URL 参数。
- **本地 dev 场景**（`make dev` 三服务在本机）：直连服务端口即可。
- 服务端口由 `.env` 配置（`AVATARLOOM_CONTROL_API_PORT` / `AVATARLOOM_RUNTIME_GATEWAY_PORT` / `STUDIO_PORT`）；隧道端口在 `.omx/scripts/tunnel.py` 固定（本地工作区，不入库）。

## 快速开始

### 环境要求

- Python 3.11+（[uv](https://docs.astral.sh/uv/)）
- Node.js 20+ 与 pnpm 11+

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
make dev        # 或 uv run python scripts/dev.py

# 浏览器打开
#   本地 dev：http://127.0.0.1:3000
#   AutoDL 隧道：http://localhost:13000/playground（推荐入口，见上方端口约定）
```

### 配置真实 Adapter（可选）

```bash
cp .env.example .env   # 填入 LLM/STT/TTS/Vision 任一 API Key
```

然后在 profile 中把对应 Block 改为 `*.openai-compatible`。GPU 部署参考 `profiles/autodl-*.yaml` 与 `docs/03-Studio部署安全与验收.md`。

## Runtime Profiles

| Profile | 说明 |
|---|---|
| `mock` | 纯 Mock，无 GPU/API Key，**默认推荐** |
| `lite-12gb` | 12GB GPU 单机（Silero + SenseVoice + Qwen3-TTS + MuseTalk） |
| `distributed` | 分布式（CPU STT + Remote LLM + Mac MLX TTS + NVIDIA Avatar） |
| `full-24gb` | 24GB+ GPU 全量（Silero + SenseVoice + VoxCPM2 + FlashHead） |

Profile 中每个 Block 可声明 `fallback` 降级目标与 `optional` 可缺席标记。

## 项目结构

```text
avatarloom/
├── apps/
│   ├── studio/              # Next.js 前端（Playground 调试台 / /show 演示窗 / 管理台）
│   ├── control-api/         # FastAPI REST（:8100）
│   └── runtime-gateway/     # FastAPI WebSocket（:8101）
├── packages/
│   ├── protocol/            # 事件 schema（Pydantic 单一来源）
│   └── sdk-python/          # Block SDK
├── runtime/
│   ├── orchestrator/        # 编排核心（Run/打断/Vision 同轮/Filler 垫音）
│   ├── session/             # 显式状态机
│   ├── event_bus/           # 事件总线（背压策略）
│   └── recorder/            # Run Recorder（事件流/指标/产物落盘）
├── blocks/                  # 各类 Block 实现
│   ├── vad|stt|llm|tts|avatar|vision|memory/
│   └── 每类含 mock + 真实 Adapter
├── profiles/                # Runtime Profile（YAML 声明组合）
├── personas/                # Persona 包（人设/音色/形象/垫音）
├── tests/                   # 单元/集成/E2E
└── deploy/                  # Docker
```

## 测试

```bash
make test              # Python + TypeScript 全量
uv run pytest tests/unit tests/integration
pnpm --dir apps/studio test -- --run
```

## 文档

- [完整设计文档](docs/00-AvatarLoom-完整设计文档.md)
- [架构与模块规范](docs/01-架构与模块规范.md)
- [事件协议、状态机与音画同步（含浏览器↔Gateway 通道协议）](docs/02-事件协议状态机与音画同步.md)
- [Studio 部署安全与验收](docs/03-Studio部署安全与验收.md)
- [Studio UI/UX 规格](docs/08-studio-ui-spec.md)
- [Studio 前端架构](docs/11-studio-frontend-architecture.md)
- [Block 开发指南](docs/block-development.md)

## 开发命令

```bash
make help      # 显示所有命令
make dev       # 启动开发环境
make test      # 全量测试
make lint      # ruff + ESLint
make type      # mypy + tsc
make smoke     # Mock 冒烟
make doctor    # 环境自检
```

## 致谢

- 音画同步与垫音机制参考 [VoxEMW](https://github.com/emwstudio/VoxEMW)（MIT）
- 语音链路基于 silero-vad / SenseVoice / VoxCPM2 / MuseTalk / FlashHead
- 记忆基于 [Mem0](https://github.com/mem0ai/mem0) 内嵌模式

## 许可证

Apache-2.0
