# MuseTalk 真口型链路 + Studio UI 重构验收补充

日期：2026-08-06
分支：`feat/autodl-rtx5090-real-e2e`
服务器：AutoDL RTX 5090 32GB / PyTorch 2.8.0+cu128 / Python 3.12

## 1. 真口型链路（在 05 报告基础上新增）

在原有 VAD → STT → LLM → TTS 真实链路之上，打通 **MuseTalk 音频驱动口型视频**：

```
用户语音 → Silero VAD → SenseVoiceSmall STT
        → DeepSeek 流式 LLM → VoxCPM2 流式 TTS
        → MuseTalk（VAE + UNet + Whisper 特征）→ 真口型 mp4
        → avatar.video.ready 事件 + 帧流
```

### 实现组件

- `blocks/avatar/musetalk.py`：真实 MuseTalk 块。TTS 期间发轻量活动帧；TTS 完成后把整段回复交给常驻 worker 渲染；渲染完成后发 `avatar.video.ready` 并逐帧回放真实口型 JPEG。
- `scripts/muse_worker.py`：常驻 worker（JSON-lines 协议），模型只加载一次，支持 v1 / v1.5，结果落盘 `<out>.json` 兜底。
- `scripts/musetalk/lite_driver.py`（musetalk 仓库内）：独立 CLI demo。
- 协议新增 `avatar.video.ready`（`AVATAR_VIDEO_READY`）。

### 关键技术适配（RTX 5090 / torch 2.8）

1. **不依赖 mmpose/face_detection**：官方 preprocessing 在 torch 2.8 环境难装；改用 mediapipe FaceMesh 计算 bbox（mediapipe 需降级 0.10.x，1.0 移除了 solutions API）。
2. **官方 BiSeNet FaceParsing 融合**：权重来自 ModelScope（`Kedreamix/Linly-Talker`），需打 `torch.load(..., weights_only=False)` 补丁（旧 .tar 格式）。
3. **融合蒙版预计算**：静态肖像只算一次 mask，逐帧用 numpy 快速融合（等价官方 get_image_blending，maxdiff<=1）。
4. **超清肖像自动缩放**：`max_side=1280`（偶数取整），避免 4000px 大图导致逐帧编码 20 倍变慢，也避免 libx264 奇数尺寸报错。
5. **全链路 fp16**：UNet/VAE/Whisper 统一 fp16，dtype 一致。

### 性能指标（RTX 5090 实测）

| 项 | 数值 |
|---|---|
| 单帧推理（batch=8, fp16） | UNet 0.153s/8帧，VAE 0.063s/8帧 |
| 渲染速度（portrait.jpg） | 49.6 fps（10s demo，5.0s 渲染） |
| 渲染速度（portrait2 4000px，max_side=1280） | 44.3 fps |
| 最终 E2E（56.6s 回复） | infer 31.6s，视频 1260 帧，总 E2E 103.9s PASS |
| 口型运动指标 | 嘴部区域帧间 diff 5.4-10.0，全帧 diff 0.2-0.4（局部动嘴、画面稳定） |
| 视频质检 | MiniMax/视频分析确认嘴部随语音张合、大致同步、面部稳定 |

### E2E 产物

- `runs/e2e-real/20260806-010140/avatar_musetalk.mp4`（4.7MB，DeepSeek+白桦音色+portrait2 男像，PASS）
- `runs/e2e-real/20260805-225311/avatar_musetalk.mp4`（3.1MB，DeepSeek+苏打音色+portrait 女像，PASS）

## 2. Studio 前端改动

- **修复 mock 之谜**：playground 原硬编码 `profile_id: "mock"`，gateway 默认也是 mock；改为 `autodl-best`（真实 GPU 配置）。
- **设计令牌**：保留黑白灰专业基调，新增单一强调色（靛蓝 `#4f46e5`）、卡片阴影、圆角体系。
- **侧边栏**：分组导航（工作台/配置/运行）+ 内联 SVG 图标 + 强调色激活态。
- **Playground**：重构为简洁对话式 Avatar 界面——角色卡片（肖像+状态+麦/播指示）、用户/助理气泡对话流、思考中流式光标、底部控制条（麦克风/打断/Debug）。
- **配置页**：Dashboard/Profiles/Personas/Avatars/Settings 统一 page-header + 卡片 + 状态徽章 + 空状态/错误态。

## 3. 运维

- 本地隧道脚本增加 SSH keepalive + 断线自动重连（`tunnel.py`）。
- 权重来源：v1 全量权重走 ModelScope（`Kedreamix/Linly-Talker`，约 3.4GB，速度 2-5MB/s）；v1.5 权重（`musetalkV15/unet.pth`）在 HF 镜像后台续传（可选质量升级，未纳入默认配置）。
