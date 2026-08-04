# AvatarLoom / 灵构完整项目开发 Prompt

你是一名资深 AI 系统架构师、实时音视频工程师、Python 后端工程师、React 前端工程师和开源项目维护者。

请从零设计并实现完整开源项目：

```text
项目名：AvatarLoom
中文名：灵构
仓库名：avatarloom
定位：Composable Digital Human Runtime
```

不要只输出方案、伪代码或小型 MVP。请按照生产级项目思维，尽可能完成真实可运行代码、目录、配置、测试、文档、示例和部署脚本。

## 核心目标

```text
Microphone → VAD → STT → Persona → Memory → LLM → TTS → Avatar → Browser
```

同时支持 Vision、Skills、Knowledge、Safety、Transport、Recorder 和 Observability。所有模型通过 Adapter 接入，Runtime 核心不得依赖具体模型实现。

## 必须实现

### Studio

Next.js、TypeScript、React、Tailwind、shadcn/ui、React Flow。实现 Dashboard、Avatar、Persona、Block Registry、Flow Builder、Profile、Session、Run、Settings 和 Realtime Playground。视觉采用白底黑字、克制专业风格。

### Control API

Python 3.11+、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic。管理 Project、Avatar、Persona、Block、Profile、Secret Reference、Session、Run 和 Artifact。开发 SQLite，生产 PostgreSQL。

### Runtime Orchestrator

实现显式状态机、Block 生命周期、事件路由、流式音频、中断、取消、超时、重试、背压、队列上限、自动降级、Persona/Voice/Avatar 切换、Audio Clock、Video Sync、Run Recorder 和 Artifact Writer。

状态：IDLE、LISTENING、TRANSCRIBING、THINKING、SPEAKING、INTERRUPTING、ERROR、CLOSED。禁止用散落布尔变量模拟。

### Block SDK

实现 Block 和 StreamingBlock 接口，支持 In-process、独立进程、HTTP Remote、WebSocket Remote、Mock、Manifest、JSON Schema、Health Check 和资源声明。

### Event Protocol

统一 Event Envelope，并为 Python 和 TypeScript 生成类型。

## 首版 Adapter

- VAD：mock、silero。
- STT：mock、sensevoice、openai-compatible；支持 CPU/CUDA/可选 ONNX INT8。
- LLM：mock、openai-compatible、ollama。
- Persona：完整 Persona Package。
- TTS：mock、openai-compatible、qwen3；预留 cosyvoice、voxcpm2、mlx-remote。
- Avatar：mock、static，并实现 musetalk 或 livetalking；预留 flashhead。
- Vision：mock、openai-compatible，且必须可缺席。

## 音画同步

音频为主时钟。Speech Frame 按音频位置消费；Idle Frame 直接显示；视频落后跳帧；视频不阻塞音频；打断时清空音频和视频；支持 audioDelayMs、videoLagFrames 和 Debug Overlay。

## Runtime Profile

实现 lite-12gb、distributed 和 full-24gb。Studio 可以加载、编辑、复制和校验。

## Run Recorder

每轮保存 manifest.json、events.jsonl、metrics.json、transcript.json、runtime-config.json、input、output 和 snapshots。记录首字、首音、首帧、总延迟、中断、错误、降级、模型版本和 Artifact。

## 可靠性

Abort/Cancel 贯穿全链路；连接关闭释放资源；外部服务有超时和降级；视频可丢帧，音频不可静默丢失；Secret 不写日志；所有相对路径基于 Workspace Root。

## API

至少实现健康、Block、Avatar、Profile、Runtime、Session、Run、Artifact REST API，以及 `WS /api/realtime`。浏览器只连接 Runtime Gateway。

## 推荐目录

```text
avatarloom/
├── apps/{studio,control-api,runtime-gateway}
├── packages/{protocol,config,sdk-python,sdk-typescript,ui}
├── runtime/{orchestrator,session,event_bus,sync,recorder,artifacts,workers}
├── blocks/{vad,stt,llm,persona,memory,tts,avatar,vision,skills,transport}
├── personas/
├── profiles/
├── docs/
├── tests/
└── scripts/
```

不得把所有逻辑放进一个文件。

## 配置与脚本

提供 `.env.example`、`avatarloom.yaml`、Profile、Demo Persona、setup/dev/start/stop/doctor/smoke/download_models 脚本。配置优先级：默认值 < YAML < .env < 环境变量 < CLI。

## 测试

单元测试覆盖配置、Persona、Manifest、Event、状态机、中断、超时、队列、同步、Artifact 和脱敏。集成测试覆盖 Mock 链路、打断、切换、降级、超时、Recorder 和 WebSocket。Playwright 覆盖创建数字人、加载 Profile、启动 Runtime、模拟对话、查看 Run 和 Artifact。

使用 ruff、mypy、pytest、pytest-asyncio、Vitest、ESLint、Playwright。

## 部署

提供 Dockerfile、Docker Compose、NVIDIA Container Toolkit、本地开发、单机 GPU、分布式 Block、HTTPS、systemd/Supervisor、健康检查和日志轮转。不得把所有服务打入一个不可维护容器。

## 执行原则

1. 直接创建完整项目代码，不只给方案。
2. 不缩减成单 HTML 或单 Python Demo。
3. Mock Profile 始终可运行。
4. 每阶段运行测试并修复。
5. 重型依赖用 Optional Extra 或独立 Adapter。
6. 不为一个模型破坏核心协议。
7. Runtime 不用模型名称判断行为。
8. 外部服务有超时和降级。
9. 重要状态全部可观测。
10. 不留下大量空函数和未解释 TODO。
11. 不停止在“下一步建议”，持续实现到可运行交付。

## 开发顺序

```text
1. Monorepo 和工具链
2. Protocol 和 Schema
3. Block SDK
4. Runtime 状态机
5. Event Bus
6. Mock 全链路
7. Run Recorder
8. Control API
9. Studio 基础
10. 浏览器实时音频
11. 真实 VAD/STT/LLM/TTS
12. 中断与取消
13. StaticAvatar
14. 实时 Avatar
15. 音画同步
16. Persona 三件套
17. Runtime Profile
18. Session 和 Run 面板
19. 部署
20. 全量测试和文档
```

## 最终交付

执行 Python 单元和集成测试、TypeScript 测试、前端构建、Playwright E2E、Docker Compose 校验、Doctor、Mock 冒烟和真实语音冒烟。最终交付完整源码、README、设计文档、测试结果、已知限制、运行与部署命令、环境模板、Demo Persona、Demo Profile、数据库迁移和 Docker Compose。

如环境允许，请创建项目、安装依赖、运行测试、修复错误、验证页面、整理目录、清理临时文件并打包为 `avatarloom-v0.1.0.zip`。
