# Studio、部署、安全与验收

## Studio 页面

- Dashboard
- Avatars
- Personas
- Block Registry
- Flow Builder
- Runtime Profiles
- Realtime Playground
- Sessions
- Runs
- Settings

## Run Recorder

```text
runs/<run_id>/
├── manifest.json
├── events.jsonl
├── metrics.json
├── transcript.json
├── runtime-config.json
├── input/
├── output/
└── snapshots/
```

记录首字、首音、首帧、总延迟、中断、错误、降级、模型版本、配置快照和 Artifact。

## 安全

- API Key 使用 Secret Reference。
- 日志脱敏。
- 浏览器不获取服务端 Secret。
- 上传素材进行 MIME、大小和内容校验。
- Persona 素材记录授权信息。
- 麦克风和摄像头显式授权。
- Artifact 支持保存期限和删除。
- 数字人输出支持 AI 标识。

## 部署

- 开发：本地进程 + SQLite。
- 单机 GPU：Docker Compose + NVIDIA Container Toolkit。
- 分布式：CPU STT、Remote LLM、Mac MLX TTS、NVIDIA Avatar。
- 生产：TLS、反向代理、健康检查、自动重启、日志轮转。

## v0.1.0 验收

1. Mock Profile 完整可运行。
2. YAML 定义数字人。
3. 浏览器完成实时语音交互。
4. 支持打断和取消。
5. 至少两个 TTS Adapter。
6. StaticAvatar 加一个实时 Avatar Adapter。
7. Avatar 失败自动降级。
8. Persona、音色和形象同步切换。
9. 每轮生成 Run 和 Artifact。
10. Lite 12GB Profile 可启动。
11. 单元、集成、E2E 和前端构建通过。
12. README、部署和新增 Block 文档完整。
