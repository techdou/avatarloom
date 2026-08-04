# AvatarLoom v0.1.0 开发计划

## 范围与诚实边界（先说清）

| 类别 | 承诺 |
|---|---|
| **代码已实现 + 测试通过** | Runtime 核心、Block SDK、状态机、Event Bus、Mock 全链路、Control API、Run Recorder、Studio 全页面骨架、Realtime Playground、OpenAI-compatible Adapter、StaticAvatar、音画同步前端、3 个 Profile、Docker Compose |
| **Mock 已验证** | Mock Profile 端到端跑通：YAML 启动 → 浏览器实时语音 → Run Recorder 落盘 → Studio 可视化 |
| **配置已验证** | 真实 GPU Adapter 的 manifest、schema、YAML profile（Silero/SenseVoice/VoxCPM2/MuseTalk） |
| **GPU 实机未验证** | Silero/SenseVoice/VoxCPM2/MuseTalk 等需 GPU 的推理代码 + 单测逻辑分支，但不在本机跑真实模型。会明确标注 |

文档处理：现有 `docs/`、`profiles/`、`templates/`、`prompts/` 全部原地保留作为设计约束；开发的工程代码进入新的 `apps/`、`packages/`、`runtime/`、`blocks/` 等目录。

## 技术栈最终定稿

- **Python 后端**：3.11+、uv workspace、FastAPI、Pydantic v2、SQLAlchemy 2 + Alembic、asyncio、structlog、httpx
- **前端**：Next.js 14（app router）+ TypeScript + Tailwind + shadcn/ui + React Flow + TanStack Query + Zustand
- **测试**：pytest + pytest-asyncio + ruff + mypy / Vitest + ESLint + Playwright
- **音频**：后端 PCM16/16kHz 流，前端 AudioWorklet 采集 + AudioContext 时钟播放（抄 VoxEMW 验证过的方案）
- **协议**：Pydantic 为单一来源 → JSON Schema → TypeScript 类型自动生成

## 目录结构（最终）

```
avatarloom/
├── apps/
│   ├── studio/                  # Next.js 全功能 Studio
│   ├── control-api/             # FastAPI Control Plane（/api/* REST）
│   └── runtime-gateway/         # FastAPI Runtime Gateway（/ws/realtime、音频流）
├── packages/
│   ├── protocol/                # Pydantic 事件 schema（单一来源）
│   ├── sdk-python/              # Block SDK Python（Block/StreamingBlock 基类）
│   ├── sdk-typescript/          # 前端 ws 客户端 + 自动生成类型
│   └── ui/                      # shadcn/ui 共享组件（Studio 引用）
├── runtime/
│   ├── orchestrator/            # 主编排器、双写、降级
│   ├── session/                 # Session Manager + 显式状态机
│   ├── event_bus/               # 内存事件总线（生产可换 Redis）
│   ├── sync/                    # Audio Clock、Speech/Idle Frame 队列
│   ├── recorder/                # Run Recorder（events.jsonl/metrics.json）
│   └── artifacts/               # Artifact Writer
├── blocks/
│   ├── vad/{mock,silero}
│   ├── stt/{mock,sensevoice,openai_compatible}
│   ├── llm/{mock,openai_compatible,ollama}
│   ├── tts/{mock,openai_compatible,qwen3,voxcpm2}
│   ├── avatar/{mock,static,musetalk,flashhead}
│   ├── vision/{mock,openai_compatible}
│   ├── persona/                 # Persona 加载器
│   ├── memory/                  # 内存记忆（v0.1 简版）
│   └── transport/               # WS Transport 实现
├── personas/
│   └── demo-assistant/          # 示例 Persona 包
├── profiles/                    # 已有 3 个 + 新增 mock.yaml
├── docs/                        # 已有设计文档 + 新增架构/Block/事件协议/状态机/部署文档
├── prompts/                     # 保留（开发指令）
├── templates/                   # 保留
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/                     # Playwright
├── scripts/
│   ├── dev.{sh,ps1}             # 一键起三服务
│   ├── doctor.py                # 环境检查
│   ├── smoke_mock.py            # Mock 全链路冒烟
│   ├── download_models.py       # GPU 模型下载（可选）
│   └── setup.sh
├── deploy/
│   ├── docker/
│   │   ├── Dockerfile.control-api
│   │   ├── Dockerfile.runtime-gateway
│   │   └── Dockerfile.studio
│   └── docker-compose.yml
├── .env.example
├── avatarloom.yaml              # 顶层启动配置
├── pyproject.toml               # uv workspace root
├── pnpm-workspace.yaml
├── package.json
└── Makefile
```

## 10 阶段实施（对应设计文档）

### 阶段 1：Monorepo 骨架 + 协议 + Block SDK
- `pyproject.toml`（uv workspace）、`pnpm-workspace.yaml`、根 `package.json`、`.gitignore`、`.env.example`、`Makefile`
- `packages/protocol/`：Pydantic 事件模型（session/audio/speech/transcript/llm/tts/avatar/vision/persona/response/block/run/artifact 13 类）、Event Envelope、JSON Schema 导出脚本 → `packages/sdk-typescript/src/generated/`
- `packages/sdk-python/`：`Block` / `StreamingBlock` 抽象基类、BlockContext、BlockManifest 模型、HealthStatus、生命周期协议（setup/warmup/process/reset/health/shutdown）
- `packages/sdk-typescript/`：ws 客户端、事件类型
- 单测：协议序列化、schema 一致性、Block 基类契约
- 验收：`uv run pytest tests/unit/protocol` 通过；`pnpm -w run build:protocol` 生成 TS 类型

### 阶段 2：状态机 + Event Bus + Mock 全链路
- `runtime/session/state_machine.py`：IDLE/LISTENING/TRANSCRIBING/THINKING/SPEAKING/INTERRUPTING/ERROR/CLOSED，纯函数转换表 + enum，所有非法转换 raise
- `runtime/event_bus/`：asyncio 内存总线，subscribe/publish，背压保护
- Mock Blocks：`blocks/vad/mock.py`、`blocks/stt/mock.py`、`blocks/llm/mock.py`（可配置回话模板）、`blocks/tts/mock.py`（生成正弦波 PCM）、`blocks/avatar/mock.py`、`blocks/vision/mock.py`
- `runtime/orchestrator/`：Session 生命周期、Block 装配（从 YAML 工厂）、VAD→STT→LLM→TTS→Avatar 主链路
- 单测：状态机全边覆盖、Event Bus 顺序/背压、各 Mock Block 输出
- 集成测试：Mock 链路端到端（注入模拟音频流 → 校验事件序列）
- 验收：`pytest tests/unit tests/integration` 全绿

### 阶段 3：Run Recorder + Artifact Writer + Control API
- `runtime/recorder/`：每 Run 一个目录（manifest.json/events.jsonl/metrics.json/transcript.json/runtime-config.json/input/output/snapshots），首字/首音/首帧/中断/降级指标
- `runtime/artifacts/`：本地存储 + 引用记录
- `apps/control-api/`：FastAPI + SQLAlchemy + Alembic，模型 Project/Avatar/Persona/BlockDefinition/RuntimeProfile/SecretReference/Session/Run/Artifact；REST CRUD + 健康检查
- Alembic 迁移
- 单测：Recorder 落盘、Artifact 写入、Control API 各端点（httpx ASGI transport）
- 验收：起 control-api 服务，curl 通

### 阶段 4：Runtime Gateway + Studio 基础
- `apps/runtime-gateway/`：FastAPI，`WS /ws/realtime`（浏览器唯一入口）、音频上行/下行、事件下行、连接生命周期管理、Session 创建/恢复
- `apps/studio/`：Next.js app router，shadcn/ui 装；页面：Dashboard、Avatars、Personas、Block Registry、Flow Builder、Runtime Profiles、Realtime Playground、Sessions、Runs、Settings；白底黑字克制风格；TanStack Query 调 control-api； Zustand 管理连接态
- Mock Profile：`profiles/mock.yaml`（纯 mock，不依赖任何外部资源）
- 验收：`pnpm dev` 起前端，页面可访问；`make dev` 三服务起来；浏览器能连上 ws

### 阶段 5：Realtime Playground + 浏览器实时音频
- Studio Realtime Playground：麦克风按钮、状态指示器、转写区、persona 切换栏、avatar canvas、debug overlay
- 前端音频：`public/worklets/recorder-worklet.js`（AudioWorklet 采集 float32 → int16 → base64）、`lib/audio/player.ts`（AudioContext 时钟调度 PCM 拼接、打断清空队列）
- 音画同步：`lib/audio/sync.ts`，audioDelayMs 应用、Speech/Idle Frame 队列、丢帧策略
- Mock 全链路：麦克风 → gateway → orchestrator → mock blocks → 回流播放
- 验收：浏览器对 Mock Profile 说话，能看到 mock 转写和听到 mock 合成正弦波

### 阶段 6：真实 OpenAI-compatible Adapter + 中断/取消
- `blocks/llm/openai_compatible.py`：chat-completions stream，逐句切分喂 TTS（参考 VoxEMW `stream_batch_sentences: 1`），关 thinking 注入
- `blocks/stt/openai_compatible.py`：`/audio/transcriptions`
- `blocks/tts/openai_compatible.py`：`/audio/speech` stream
- 单测：用 httpx MockTransport 模拟 OpenAI 响应，覆盖流式分块、错误、超时
- 中断/取消：`INTERRUPTING` 状态完整实现，`asyncio.CancelledError` 贯穿 LLM/TTS 流，音频队列清空，Avatar reset
- 验收：豆哥填 `OPENAI_API_KEY` 后能跑真实对话；无 Key 时 mock server 测试通过

### 阶段 7：StaticAvatar + 音画同步 + Persona 切换
- `blocks/avatar/static.py`：静态肖像 + 可选 idle 视频循环；接管 Speech/Idle Frame 协议
- Persona 三件套加载器：`blocks/persona/loader.py`，解析 persona.yaml + persona.md + voice ref + avatar asset
- Persona 切换：`session.update_persona()` 同步切换 LLM instructions、TTS voice、Avatar asset、Memory namespace
- 音画同步：StaticAvatar 发 Speech Frame（静态图 + 口型动画占位）+ Idle Frame；前端按时钟消费
- 单测：Persona 解析、切换原子性
- 验收：Studio 切 persona，链路同步切

### 阶段 8：真实 GPU Adapter（代码 + 单测，不实机）
- `blocks/vad/silero.py`：torch 加载 silero-vad，streaming 接口，chunk 处理
- `blocks/stt/sensevoice.py`：FunASR SenseVoiceSmall，CPU/CUDA
- `blocks/tts/qwen3.py`、`blocks/tts/voxcpm2.py`：流式合成 + 重采样到 16kHz
- `blocks/avatar/musetalk.py`：参考图 + 音频 → JPEG 帧流
- `blocks/vision/openai_compatible.py`：多模态 API
- 重依赖隔离：每个 adapter 的 `pyproject.toml` 用 `optional-dependencies`，运行时导入失败给友好错误并触发降级
- 单测：纯逻辑分支（重采样数学、chunk 边界、降级路径），不加载真实模型
- 验收：`pytest tests/unit/blocks` 通过；import 失败时降级路径工作

### 阶段 9：Runtime Profiles + 诊断 + Docker
- 完善 `profiles/mock.yaml`、`lite-12gb.yaml`、`distributed.yaml`、`full-24gb.yaml`
- Profile 加载/校验：Studio 可加载、编辑、复制、校验（schema 一致性、Block 引用存在性）
- `scripts/doctor.py`：检查 Python/Node 版本、可选依赖、磁盘、端口、API Key（不打印值）
- `scripts/smoke_mock.py`：起 Mock 链路 + 注入模拟音频 + 校验事件序列 + 落盘 Run
- Docker：三服务各一个 Dockerfile + `docker-compose.yml`（含 SQLite 卷、NVIDIA runtime 可选 profile）
- 验收：`docker compose config` 校验通过；`python scripts/doctor.py` 报告清晰

### 阶段 10：全量测试 + 文档 + 清理
- 补齐单元/集成/E2E 测试
- Playwright E2E：创建 Avatar → 加载 Profile → 启动 Runtime → 模拟对话（mock 模式）→ 查看 Run/Artifact
- 文档：`docs/architecture.md`、`docs/block-development.md`、`docs/event-protocol.md`、`docs/state-machine.md`、`docs/deployment.md`、根 `README.md`（重写为用户向）、`CHANGELOG.md` 更新
- `.env.example`、本地启动脚本（dev/stop/doctor/smoke）
- Lint/类型检查：ruff + mypy / ESLint + tsc 全绿
- 验收：完整测试矩阵通过

## 每阶段闭环（严格遵守）

每个阶段结束前执行：
1. `uv run pytest tests/` 相关部分 → 修到全绿
2. `pnpm test && pnpm lint` 前端 → 修到全绿
3. `uv run ruff check . && uv run mypy packages runtime blocks` → 修到无错
4. 更新该阶段涉及的 `docs/`
5. `git add -A && git commit -m "phase N: <描述>"`
6. 进入下一阶段

## 最终交付清单（对应验收 15 条）

1. ✅ YAML 启动数字人（`avatarloom.yaml` + persona 包）
2. ✅ 浏览器实时语音交互（Realtime Playground + ws）
3. ✅ VAD→STT→LLM→TTS 主链路（Mock 全验证 + OpenAI-compatible 真实可跑）
4. ✅ 流式/打断/取消/资源释放
5. ✅ Persona/音色/形象同步切换
6. ✅ StaticAvatar + MuseTalk Adapter（StaticAvatar 实跑，MuseTalk 代码+单测）
7. ✅ Avatar/Vision 失败自动降级不阻断语音
8. ✅ Mock Profile 永远可跑
9. ✅ Lite 12GB / Distributed / Full 24GB+ Profile
10. ✅ Run + 事件 + 指标 + Artifact
11. ✅ Studio + Control API + Runtime Gateway
12. ✅ 单元/集成/E2E/诊断/冒烟
13. ✅ 本地原生启动（`make dev` / `scripts/dev.sh`）
14. ✅ Docker Compose 可选（不强制）
15. ✅ 目录规范 + 文档完整 + 可继续二开

## 最终报告会明确区分

- Python lint/类型/测试 结果
- TypeScript lint/测试/构建 结果
- Playwright E2E 结果
- Mock 全链路冒烟 结果
- Docker Compose 校验 结果
- Doctor 检查 结果
- 真实 GPU 模型推理 → **明确标注"代码已实现 / GPU 实机未验证"**

## 风险与诚实告知

1. **Next.js 全功能 Studio 工作量大**：Dashboard/Flow Builder/Sessions/Runs 10 个页面都做，但 Flow Builder（React Flow 拖拽编排）会做简化版（展示 + 编辑现有 profile，不做完全自由拖拽生成）
2. **Playwright E2E 需要真实浏览器**：本机环境若 Playwright 装不上 chromium，会明确报告"E2E 代码已写但未在 CI 跑通"
3. **真实 GPU Adapter 不实机验证**：豆哥已确认接受
4. **会话上下文长度**：10 阶段在一个会话里跑完，后半段可能触发上下文压缩。我会用 git commit 锁住每阶段产物，压缩后仍能继续

确认无误后我开始执行阶段 1。