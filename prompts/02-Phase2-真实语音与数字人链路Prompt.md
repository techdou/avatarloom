# Phase 2：真实语音与数字人链路 Prompt

在已通过测试的 Phase 1 项目上继续开发，不重写正确的基础协议和 Runtime。

接入 Silero CPU、SenseVoice CPU/CUDA/可选 ONNX INT8、OpenAI-compatible 流式 LLM、Qwen3-TTS 0.6B Base、StaticAvatar 和 MuseTalk/LiveTalking。保留 OpenAI-compatible TTS、Mock TTS，并预留 CosyVoice、VoxCPM2、MLX Remote 和 FlashHead。

前端使用 AudioWorklet 采集 16kHz PCM，支持流式播放、打断、音频主时钟、Idle/Speech Frame、Debug Overlay。

验证 lite-12gb、distributed、full-24gb Profile。增加真实 Adapter 配置测试、可选依赖测试、无 GPU 跳过机制和模拟 WAV E2E。完成后运行全量测试、前端构建和 Docker Compose 校验，并打包 ZIP。
