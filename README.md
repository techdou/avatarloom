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
- **Mock 永远可跑**：无 GPU/Docker/API Key 时降级到 mock，仍能跑通完整开发回归链路
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

### Mock 快速开始（默认）

```bash
# 一键冒烟（不起服务，验证完整 Mock 事件链）
uv run python scripts/smoke_mock.py

# 启动三服务（Control API + Runtime Gateway + Studio）
make dev

# 浏览器打开
#   本地：http://127.0.0.1:3000/playground
```

默认档位是 `mock`，无需 GPU 或 API Key。启动真实 12GB GPU 链路：

```bash
make setup-gpu
AVATARLOOM_DEFAULT_PROFILE=lite-12gb make dev
```

### 配置真实 Adapter

```bash
cp .env.example .env   # 填入 LLM/STT/TTS/Vision 任一路 API Key
```

然后在 profile 中把对应 Block 改为 `*.openai-compatible` 等真实实现；GPU 部署参考 `profiles/autodl-*.yaml`。

### 运行时 Profile

| Profile | 说明 |
|---|---|
| `mock` | **默认档位**，纯 Mock，无 GPU/API Key，适合开发与 CI |
| `lite-12gb` | 12GB GPU 单机真实链路，需显式启用 |
| `distributed` | 分布式（CPU STT + Remote LLM + Mac MLX TTS + NVIDIA Avatar） |
| `full-24gb` | 24GB+ GPU 全量 |
| `autodl-best` | AutoDL 云 GPU 最佳实践档 |

Control API 数据库是运行时 Profile/Persona 的在线事实源：首次启动从仓库
`profiles/`、`personas/` 初始化，Studio 修改后 Gateway 通过 Control API 读取；文件仅作为
本地镜像和控制面离线时的只读回退。Runs/Sessions 由 Gateway Recorder 落盘，Control API
直接索引同一 `AVATARLOOM_RUNS_ROOT`，因此 Studio 历史页与真实运行记录一致。

## 配置与安全

- 环境变量模板见 `.env.example`（含全部可选 Key 与说明）；**真实密钥只放本地 `.env`，绝不入库**
- 鉴权默认 **fail-closed**：生产必须设置 `AVATARLOOM_API_TOKEN`；Studio 通过服务端代理注入 HTTP Bearer，并签发 60 秒 WS ticket，长期 token 不进入浏览器 bundle。本地开发可用 `AVATARLOOM_AUTH_DISABLED=1` 显式关闭
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
# 默认 Mock：非 root、frozen lockfile、无需 GPU
docker compose -f deploy/docker-compose.yml up -d --build

# 真实 GPU：安装 gpu-full extras、申请 NVIDIA GPU、默认 lite-12gb
AVATARLOOM_API_TOKEN='<随机长密钥>' \
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.gpu.yml up -d --build
```

生产环境必须设置 `AVATARLOOM_API_TOKEN` 并设 `AVATARLOOM_AUTH_DISABLED=0`。旧入口
`deploy/docker/docker-compose.yml` 仅保留向后兼容，新部署统一使用上述 canonical 文件。

## 仓库规范

- **密钥/私密信息不入库**：`.env` 系列、`*.key`/`*.pem`/`*.p12` 等均被 `.gitignore` 排除，只有 `*.example` 模板入库
- **开发软件配置目录不上传**：`.venv/`、`.zcode/`、`.omx/`、`.agents/`、IDE 配置、`.npmrc` 等均不入库
- **文档不纳入版本控制**：`docs/` 仅本地维护，面向用户的说明统一在根目录 `README.md`

## 许可证

Apache-2.0
