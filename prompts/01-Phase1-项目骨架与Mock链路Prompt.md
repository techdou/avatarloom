# Phase 1：项目骨架与 Mock 全链路 Prompt

基于 AvatarLoom 设计文档完成第一阶段，暂不依赖 GPU 和真实重型模型，但必须完整可运行。

完成 Monorepo、Protocol、Block SDK、Manifest、状态机、Event Bus、Mock VAD/STT/LLM/TTS/Avatar/Vision、Runtime Gateway、Run Recorder、Artifact Writer、SQLite Control API、Studio 基础页面、Realtime Playground、单元/集成/E2E 和 Docker Compose。

Mock 链路：模拟音频 → Mock VAD → Mock STT → Persona → Mock LLM 流式 → Mock TTS PCM → Static/Mock Avatar → 浏览器。

必须验证打断、状态转换、Persona 切换、Avatar 降级、Block 超时、Run 落盘、WebSocket 断开释放和 Run 时间线。

禁止伪代码、单文件堆叠、不运行测试或因为没有真实模型就跳过流式协议。完成后输出目录树、运行命令、测试结果、已知限制并打包 ZIP。
