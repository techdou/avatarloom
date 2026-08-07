# VoxEMW 对照与借鉴

> 目的：AvatarLoom 是 [VoxEMW](https://github.com/emwstudio/VoxEMW)（152★，MIT）的模块化重构版。
> 本文沉淀上游实现要点与我们的对照结论，避免每次重新读对方代码。
> 同步时间：2026-08-07（对方 main 分支）。

---

## 1. 项目映射

| VoxEMW | AvatarLoom | 说明 |
|---|---|---|
| CPU orchestrator（WS :8000） | `runtime/orchestrator` + Gateway :8101 | 职责相同 |
| `web/assistant.js`（无构建前端） | `apps/studio`（Next.js） | 播放器逻辑由 `lib/audio/{player,sync}.ts` 继承 |
| `configs/assistant.yaml` | `profiles/*.yaml` | Block 声明式组合 |
| `voxemw/pipeline/`（VAD/STT/TTS） | `blocks/vad|stt|tts/*` | 同栈：silero / SenseVoice / VoxCPM2 |
| AVTR-1（TensorRT，0.2s 生成块） | `blocks/avatar/{musetalk,flashhead}` | 不同渲染路线 |
| `voxemw/memory.py`（Mem0 内嵌） | `blocks/memory/`（stub，未实现） | 见 §4 借鉴点 |
| Mem0：DeepSeek 抽取 + bge-m3 + 内嵌 Qdrant | — | 本地零服务依赖方案 |

**上游实测延迟分解（RTX 4090D）**：VAD 端点 0.5s → STT 0.1s → LLM 首句 1.4s → TTS 首音 0.1s → 口型缓冲 0.35s，端到端 ~2.4s。
**用途：AutoDL E2E（5090）的期望基准**——我们首字/首音/首帧落盘指标可直接与这组数对比，明显劣化即视为异常信号。

## 2. 已对齐（不用动）

| 机制 | VoxEMW | AvatarLoom | 状态 |
|---|---|---|---|
| PCM 时钟调度 | `nextStartTime` 单调游标 | `player.ts` 同款 | ✅ |
| 音频主时钟驱动视频 | `target = pos*25 - lag` | `sync.ts` 同款 | ✅ |
| 落后 >1s 跳帧追平 | 跳最新保同步 | `maxAhead = fps` | ✅ |
| idle 帧节流直画 | ≥38ms 间隔 | 40ms 节流 | ✅ |
| rAF 驱动消费 | setInterval 在 iOS 漂移 → rAF | rAF | ✅ |
| 打断清空播放/帧队列 | flushPlayback（关 ctx 重建） | `interrupt()`（停源重置游标，更轻） | ✅ 等价 |
| TTS 语速补偿 | rate=0.886 | `voxcpm2.py` 同款 | ✅ |
| 帧供给超前 | avatarAudioDelay ~0.35s（AVTR-1） | audioDelayMs=600ms | ✅ 参数按链路调 |

## 3. 已借鉴落地（本文档同步时顺手修）

### 3.1 帧队列深度 25 → 100

- **上游经验**："播放链会积压（实测 3-4s）"——VoxCPM2 合成速度 ~2x 实时，帧必然积压；`FRAME_QUEUE_MAX=1000`（~40s），策略"嘴型最多滞后，绝不超前"。
- **我们原状**：`sync.ts maxQueueSize = 25`（1s）——真实链路上会一路 drop_oldest，口型仍同步但画面顿挫跳帧。
- **修改**：默认 25 → **100**（4s 窗口），保留 drop_oldest 兜底。开卡后若观察到顿挫，第一嫌疑人已排除。

### 3.2 同步参数 URL 可调（`?adelay=` / `?vlag=`）

- **上游做法**：`?debug=1` HUD + `?adelay=` / `?vlag=` 直接调参——现场调优不改代码。
- **修改**：`useRealtimeSession` 在 `connect()` 时读 URL 参数覆盖 `audioDelayMs`（PcmPlayer/AVMux）与 `videoLagFrames`（AVMux）。AutoDL 调音画同步时直接改 URL 试值。
- 用法：`/playground?adelay=450&vlag=-3`（负值=口型滞后补偿，对齐上游 -3 帧经验值）。

## 4. 开卡后借鉴路线（未做，按优先级）

### 4.1 Filler 沉吟链路（高价值， personas 目录已预留）

- **上游做法**：倾听/思考时**循环 persona 预合成嘟囔音频**驱动 idle 帧（tag 0x00）——"真实沉吟/附和微动"。用户说完到 LLM 首字的 1-2s 空白期数字人不是静止的。
- **我们现状**：`personas/demo-assistant/fillers/` 目录已存在（空）；avatar idle 帧链路已通。
- **落地草案**：persona 包预合成 `fillers/*.wav`；orchestrator 在 `transcribing/thinking` 状态让 avatar/TTS 播 filler（不走实时合成，零延迟成本）；response 开始即停。
- **前置坑**：见 4.2——上 filler 前必须先解决连播重锚。

### 4.2 连播回复不重锚音频基准（filler 前置依赖）

- **上游经验**：filler→正式回复**连播**时 `responseAudioBase` 不重锚——否则前一条回复的帧被丢弃、视频 mid-play 冻结（上游注释："注入式连播回复跳过重锚，2026-08-04 终版"）。
- **我们现状**：`player.ts` 在 `scheduledSources` 空时自动重锚——连播第二条首 chunk 会触发重锚，**与上游踩过的坑完全相同**。
- **落地草案**：base 只在显式 reset（interrupt/disconnect/新 run）后重锚；同一 run 内连播保持时钟连续。改 `PcmPlayer.enqueue` 自动锚逻辑 + hook 在新 run 边界显式控制。
- **注意**：动核心同步逻辑，必须在 Mock + 真实链路双重验证后上，不要和 filler 同一天改。

### 4.3 Memory block（Mem0 内嵌模式，`blocks/memory/` stub 的正解）

- **上游模板**（`voxemw/memory.py`，可直接照抄架构）：
  - Mem0 Python SDK **内嵌模式**（零独立服务）；DeepSeek 做事实抽取（temperature 0）；`bge-m3` 本地 embedding；**内嵌 Qdrant 文件存储**（`data/memory`）。
  - **读**：session 开始 `search(user_id, agent_id)`（per-persona 隔离）→ 每条截 80 字防稀释人设 → 一次性追加到 persona instructions，不进语音轮。
  - **写**：`response.done` 后 `asyncio.to_thread` 异步抽取——**不占语音延迟**。
  - **降级**：disabled/无 key/初始化异常 → `None` 静默跳过，对话链路零影响。
- **落地位置**：`blocks/memory/mem0_local.py` + orchestrator 在 run 边界调写、session 边界调读。

### 4.4 上游升级回归方法（`docs/upgrade-regression.md`）

- 上游对 huggingface/speech-to-speech 等依赖有升级回归清单。等我们建 CI（AL-QA-001）时可参考其"升级 → 回归 → 实测延迟对比"流程。

## 5. 明确不借鉴

- **AVTR-1 TensorRT 渲染服务**：与 musetalk/flashhead 路线不兼容，无代码可搬（同步策略已吸收）。
- **assistant.js 无构建前端**：Studio 已远超（Next.js + 调试面板）。
- **双写音频总线**：VoxEMW orchestrator 把 TTS 音频双写给浏览器和 avatar；AvatarLoom 用事件订阅（`tts.audio.*`）达到同等效果且可多方订阅，不改。

---

**下次同步触发**：VoxEMW main 有实质更新（watch releases）；或我们落地 4.1/4.2/4.3 后回填实际效果对比。
