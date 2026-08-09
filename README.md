# AvatarLoom / 灵构

> Composable Digital Human Runtime —— 可组合、可降级的实时 AI 数字人运行时与管理平台。

AvatarLoom 将 VAD、STT、LLM、TTS、Avatar、Vision、Memory、Persona 等能力拆分为可替换的 Block，由统一 Runtime Orchestrator 通过事件总线编排；YAML Profile 声明式组合，换组件不改代码。

## 核心特性

- **模块化架构**：所有能力都是 Block，YAML 声明式组合，支持 fallback 降级与 optional 缺省
- **实时语音对话**：VAD → STT → LLM → TTS → Avatar 完整流式链路
- **流式输出 + 打断**：LLM 流式 token、TTS 流式 PCM，用户随时打断且任务真正取消
- **音画同步**：音频主时钟，Avatar 帧从属播放位置，连播回复画面不冻结
- **视觉感知**：触发词命中 → 截帧 → 多模态分析 → 同轮注入回答
- **长期记忆**：Mem0 内嵌记忆（本地向量库，可选启用，默认关闭）
- **Persona 一体**：人设/音色/形象/垫音/记忆按包切换
- **降级容错**：Block 失败走 fallback 链路降级并显式记录，不静默
- **Mock 永远可跑**：不依赖 GPU/Docker/API Key 的完整开发回归链路
- **可观测**：每轮 Run 落盘事件流、首字/首音/首帧延迟、降级路径与产物

## 架构总览

```text
avatarloom/
├── apps/
│   ├── studio/            # Next.js 前端（Playground / Show / 管理台）
│   ├── control-api/       # FastAPI REST 控制面（8100）
│   └── runtime-gateway/   # FastAPI WebSocket 实时入口（8101）
├── packages/
│   ├── protocol/          # 事件 schema 单一来源（Pydantic + JSON Schema + TS 类型生成）
│   ├── sdk-python/        # Block SDK（抽象基类 + 生命周期契约）
│   └── sdk-typescript/    # TS SDK（gen_protocol.py 生成）
├── runtime/
│   ├── orchestrator/      # 编排核心（Run / 打断 / Vision 同轮 / Filler 垫音）
│   ├── session/           # 显式状态机
│   ├── event_bus/         # 事件总线（背压策略）
│   └── recorder/          # Run Recorder（事件流 / 指标 / 产物落盘）
├── blocks/                # vad / stt / llm / tts / avatar / vision / memory ...
├── profiles/              # Runtime Profile（YAML 声明式组合）
├── personas/              # Persona 包
├── deploy/                # Docker（镜像 + Compose）
├── scripts/               # dev / doctor / smoke_mock / gen_protocol / GPU workers
└── tests/                 # 单元 / 集成 / E2E
```

## 快速开始

### 环境要求

- Python 3.11+（推荐 [uv](https://docs.astral.sh/uv/)）
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

# 启动三服务（Control API + Runtime Gateway + Studio）
make dev

# 浏览器打开
#   本地：http://127.0.0.1:3000/playground
```

### 配置真实 Adapter（可选）

```bash
cp .env.example .env   # 填入 LLM/STT/TTS/Vision 任一路 API Key
```

然后在 profile 中把对应 Block 改为 `*.openai-compatible` 等真实实现；GPU 部署参考 `profiles/autodl-*.yaml`。

### 运行时 Profile

| Profile | 说明 |
|---|---|
| `mock` | 纯 Mock，无 GPU/API Key，默认推荐 |
| `lite-12gb` | 12GB GPU 单机 |
| `distributed` | 分布式（CPU STT + Remote LLM + Mac MLX TTS + NVIDIA Avatar） |
| `full-24gb` | 24GB+ GPU 全量 |

## 配置与安全

- 环境变量模板见 `.env.example`（含全部可选 Key 与说明）；**真实密钥只放本地 `.env`，绝不入库**
- 鉴权默认 **fail-closed**：未配置 `AVATARLOOM_API_TOKEN` 时所有端点返回 401 / WS 握手拒绝；本地开发可用 `AVATARLOOM_AUTH_DISABLED=1` 显式关闭（`make dev` 已自动设置）
- GPU 会话结束后 Gateway 默认自重启（`AVATARLOOM_SELF_RESTART=1`）以清理 CUDA fork 状态；无 supervisor 的部署可设 `0` 关闭
- 端口约定：Studio `3000`、Control API `8100`、Runtime Gateway `8101`（均可用环境变量覆盖）

## 测试与质量门禁

```bash
make lint      # ruff + ESLint
make type      # mypy + tsc
make test      # Python + TypeScript 全量
make smoke     # Mock 冒烟
make doctor    # 环境自检
```

## 部署

```bash
# Docker Compose 一键起三服务（非 root、frozen lockfile 构建）
docker compose -f deploy/docker/docker-compose.yml up -d --build
```

生产环境必须设置 `AVATARLOOM_API_TOKEN`（或按部署拓扑注入共享密钥），不要依赖默认开发模式。

## 仓库规范

- **密钥/私密信息不入库**：`.env` 系列、`*.key`/`*.pem`/`*.p12` 等均被 `.gitignore` 排除，只有 `*.example` 模板入库
- **开发软件配置目录不上传**：`.venv/`、`.zcode/`、`.omx/`、`.agents/`、IDE 配置、`.npmrc` 等均不入库
- **文档不纳入版本控制**：`docs/` 仅本地维护，面向用户的说明统一在根目录 `README.md`

## 许可证

Apache-2.0
