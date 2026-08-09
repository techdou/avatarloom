# AvatarLoom / 灵构

> **Composable Digital Human Runtime**
> 将声音、人格、形象与记忆，编织成可运行的数字人。

AvatarLoom 是一个模块化、积木式的实时 AI 数字人运行时平台。它把 VAD、STT、LLM、TTS、Avatar、Vision、Memory、Persona 等能力拆分为可替换的 **Block**，由统一的 Runtime Orchestrator 通过事件总线编排。

## 核心特性

- **积木式架构** — 所有能力都是 Block，YAML 声明式组合，换组件不改代码
- **实时语音对话** — VAD → STT → LLM → TTS → Avatar 完整流式链路
- **流式输出 + 打断** — LLM 流式 token、TTS 流式 PCM，用户随时打断且任务真取消
- **音画同步** — 音频主时钟，Avatar 帧从属播放位置；连播回复画面不冻结
- **视觉感知** — 触发词命中 → 截帧 → 多模态分析 → 同轮注入回答
- **长期记忆** — Mem0 内嵌记忆（本地向量库，可选启用，默认关闭）
- **Persona 一体** — 人设 / 音色 / 形象 / 垫音 / 记忆按包切换
- **降级容错** — Block 失败按 fallback 链降级并显式记录，不静默
- **Mock 永远可跑** — 不依赖 GPU / Docker / API Key 的完整开发回归链路
- **可观测** — 每轮 Run 落盘事件流、首字 / 首音 / 首帧延迟、降级路径与产物

## 快速开始

### 环境要求

| 依赖 | 版本 | 安装方式 |
|---|---|---|
| Python | ≥ 3.11 | [uv](https://docs.astral.sh/uv/)（推荐）或系统 Python |
| Node.js | ≥ 20 | [nodejs.org](https://nodejs.org) |
| pnpm | ≥ 11 | `npm install -g pnpm` |

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

无需 GPU、无需 API Key，开箱即用：

```bash
# 一键冒烟（不起服务，直接跑 Mock 链路）
uv run python scripts/smoke_mock.py

# 启动三服务（Studio + Control API + Runtime Gateway）
make dev

# 浏览器打开 http://127.0.0.1:3000
```

### 配置真实 Adapter（可选）

```bash
cp .env.example .env   # 填入 LLM / STT / TTS / Vision 任一 API Key
```

然后在 profile 中把对应 Block 改为 `*.openai-compatible`，或选择 GPU profile（见下方）。

## 端口约定

三服务默认绑 `127.0.0.1`，用户访问方式取决于部署形态：

| 服务 | 服务端口 | 本地 dev | Docker Compose | 远程 GPU 服务器 |
|---|---|---|---|---|
| Studio | 3000 | `http://127.0.0.1:3000` | `127.0.0.1:3000` | SSH 隧道 → `localhost:13000` |
| Control API | 8100 | `http://127.0.0.1:8100` | `127.0.0.1:8100` | SSH 隧道 → `localhost:18100` |
| Runtime Gateway | 8101 | `ws://127.0.0.1:8101/ws/realtime` | `127.0.0.1:8101` | SSH 隧道 → `localhost:18101` |

> **安全提示**：未设 `AVATARLOOM_API_TOKEN` 时鉴权关闭（仅适合本地 dev）。远程部署务必设置 token 并通过 SSH 隧道访问，不要直接暴露端口到公网。

## 部署

### Docker Compose

```bash
# 默认 Mock profile，无需 GPU
docker compose -f deploy/docker-compose.yml up

# 真实 GPU：设 profile + API Key + token
AVATARLOOM_DEFAULT_PROFILE=autodl-best \
AVATARLOOM_API_TOKEN=<你的随机token> \
LLM_API_KEY=<你的key> \
docker compose -f deploy/docker-compose.yml up
```

### GPU 服务器（AutoDL / 自建）

```bash
# 服务器上一键安装环境
bash scripts/autodl_setup.sh

# 启动服务
bash scripts/autodl_start.sh

# 本地 SSH 隧道（安全访问，不暴露端口）
ssh -L 13000:127.0.0.1:3000 -L 18100:127.0.0.1:8100 -L 18101:127.0.0.1:8101 root@<server>
```

## Runtime Profiles

| Profile | 说明 | GPU 需求 |
|---|---|---|
| `mock` | 纯 Mock，无 GPU / API Key | 无 |
| `lite-12gb` | Silero + SenseVoice + Qwen3-TTS + MuseTalk | 12GB VRAM |
| `autodl-best` | 真实 GPU 全链路（AutoDL RTX 5090 验证） | 24GB+ VRAM |
| `full-24gb` | Silero + SenseVoice + VoxCPM2 + FlashHead | 24GB+ VRAM |
| `distributed` | CPU STT + Remote LLM + Mac MLX TTS + NVIDIA Avatar | 混合 |

Profile 中每个 Block 可声明 `fallback` 降级目标与 `optional` 可缺席标记。

## 项目结构

```text
avatarloom/
├── apps/
│   ├── studio/              # Next.js 前端（Playground / Showcase / 管理台）
│   ├── control-api/         # FastAPI REST (:8100)
│   └── runtime-gateway/     # FastAPI WebSocket (:8101)
├── packages/
│   ├── protocol/            # 事件 schema（Pydantic 单一来源）
│   ├── sdk-python/          # Block SDK（Python）
│   └── sdk-typescript/      # TS SDK（gen_protocol.py 生成）
├── runtime/
│   ├── orchestrator/        # 编排核心（Run / 打断 / Vision 同轮 / Filler 垫音）
│   ├── session/             # 显式状态机
│   ├── event_bus/           # 事件总线（背压策略）
│   └── recorder/            # Run Recorder（事件流 / 指标 / 产物落盘）
├── blocks/                  # 各类 Block 实现
│   ├── vad/ stt/ llm/ tts/ avatar/ vision/ memory/ persona/
│   └── 每类含 mock + 真实 Adapter
├── profiles/                # Runtime Profile（YAML 声明组合）
├── personas/                # Persona 包（人设 / 音色 / 形象 / 垫音）
├── scripts/                 # 开发 / 部署 / 诊断脚本
├── tests/                   # 单元 / 集成测试
└── deploy/                  # Docker Compose + Dockerfile
```

## 开发

### 常用命令

```bash
make help      # 显示所有命令
make dev       # 启动开发环境（三服务）
make test      # 全量测试（Python + TypeScript）
make lint      # ruff + ESLint
make type      # mypy + tsc
make smoke     # Mock 冒烟
make doctor    # 环境自检
```

### 质量门禁

代码变更需通过全量门禁：

```bash
# Python
ruff check runtime/ blocks/ apps/ scripts/ tests/ packages/
mypy runtime/ blocks/ apps/control-api/src apps/runtime-gateway/src
pytest tests/ -q

# TypeScript
pnpm --filter @avatarloom/studio test
pnpm --filter @avatarloom/sdk-typescript test
cd apps/studio && npx tsc --noEmit
```

### 开发新 Block

1. 在 `blocks/<category>/` 下创建文件，继承 `Block` 基类
2. 实现 `manifest()` / `setup()` / `process()` / `reset()` / `shutdown()`
3. 在 `runtime/orchestrator/__init__.py` 用 `register_block()` 注册
4. 在 profile YAML 里引用

重型依赖（torch / funasr 等）用 optional extras 隔离：`uv sync --extra silero`。

## 致谢

- 音画同步与垫音机制参考 [VoxEMW](https://github.com/emwstudio/VoxEMW)（MIT）
- 语音链路基于 silero-vad / SenseVoice / VoxCPM2 / MuseTalk / FlashHead
- 记忆基于 [Mem0](https://github.com/mem0ai/mem0) 内嵌模式

## 许可证

[Apache-2.0](LICENSE)
