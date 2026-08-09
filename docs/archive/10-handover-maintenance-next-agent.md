# AvatarLoom 维护交接文档 — 下一 Agent

> **状态回填（2026-08-07）**：本文 §5 问题清单大面积已闭环。两轮修复：
> - `c08feab`（并行工作）：AL-P1-001/002/003/007/009 + 前端 0x00 tag / wss / vision.frame_error。
> - 本轮 5 个 commit（`aa291c9`/`32325fa`/`4c8c43b`/`b1d7cd3` + docs）：AL-P1-005（含重发循环陷阱修复）、AL-P1-006（协作式取消）、AL-P2-003、AL-P1-011（节流+锁）、AL-P2-009、AL-P2-006、AL-P2-007、AL-P1-004、AL-E2E-001/002、fallback 递归防护。
> 验证：237 pytest + 28 vitest + tsc/build 全绿；mock E2E 本地 PASS。
> **仍开放**：AL-P1-008（状态隔离决策）、AL-P1-010（gateway setup 清理）、AL-P2-001/002/004/008/010/011、AL-QA 系列（CI/E2E/协议测试）、真实 GPU 验收（下一步，开卡）。
> 以下 §5 清单保留历史原貌，状态以本回填为准。

---

> 交接时间：2026-08-06（Asia/Shanghai）
> 交接人：主对话 Agent
> 接棒人：下一维护/开发 Agent
> 一句话：**feature 分支已本地 fast-forward 合入 main；最新 Vision 功能的构建、协议导入和 TTS 下行解析阻断已修复，Mock/集成测试与 Studio 检查通过；真实 GPU、Vision 同轮编排、多会话隔离和 CI 仍待后续工作。**

---

## 0. 当前状态摘要

| 项目 | 当前状态 | 证据/备注 |
|---|---|---|
| 本地 `main` | ✅ 已更新 | `main` 与 feature 同指同一最新提交（以 `git log` 为准） |
| 合并方式 | ✅ fast-forward | `git merge --ff-only feat/autodl-rtx5090-real-e2e`，无 merge commit |
| 远端 `origin/main` | ⏳ 未更新 | 本轮没有 push；仍在 `165b4b5` |
| 远端 feature | ⏳ 落后 2 个本地提交 | `origin/feat/autodl-rtx5090-real-e2e` 仍在 `2379d53` |
| Studio TypeScript | ✅ 通过 | `pnpm --dir apps/studio exec tsc --noEmit` |
| Studio Vitest | ✅ 10 passed | 2 个测试文件，`pnpm --dir apps/studio test -- --run` |
| Python unit/integration | ✅ 224 passed, 2 skipped | `uv run pytest tests/unit tests/integration` |
| Python Ruff（本轮相关文件） | ✅ 通过 | 已检查 Orchestrator、Protocol、Gateway |
| Mock 主链路 | ✅ 有测试覆盖 | VAD → STT → LLM → TTS → Avatar |
| Vision 视觉链路 | ⚠️ 代码已接入 | 本机未做真实 Vision API/摄像头 E2E |
| AutoDL GPU 链路 | ⏳ 待实机复验 | VoxCPM2/MuseTalk/FlashHead 依赖本机不可验证 |
| CI | ❌ 未建立 | 没有 GitHub Actions/GitLab CI/pre-commit |
| 浏览器 E2E | ❌ 未建立 | `tests/e2e/` 没有正式 spec |
| Studio Blocks Explorer | ⏳ Stub | `apps/studio/app/(studio)/blocks/page.tsx` 标有 P5 TODO |

**重要：** 本地代码现在可以通过本轮已执行的 Python 和 Studio 基础检查，但这不等于真实 GPU 链路已经验收。凡是没有在 AutoDL 上实际跑过的结果，都必须标记为“待实测”。

---

## 1. Git 版本和合并记录

### 1.1 当前提交

```text
文档提交：dc493ec（初版）
后续文档修正提交：80a6ba5
```

前两个关键提交：

```text
17bda7c feat(vision): 完整视觉链路——触发词→截帧→多模态分析→LLM注入
2379d53 fix(review2): STT subscription CRITICAL + 4 HIGH + LLM timeout + asset precheck
```

`main` 从 `165b4b5` 线性快进到当前最新文档提交。代码修复提交为 `3ad4a62`，交接文档初版提交为 `dc493ec`，随后修正提交为 `80a6ba5`。当前 feature 和 main 指向同一个本地提交，没有创建多余的 merge commit，也没有删除 feature 分支。

### 1.2 本轮未执行的远端操作

本轮**没有**执行：

- `git push`；
- 删除 feature 分支；
- 改写提交历史；
- 修改或提交 `.omx` 下的凭据/临时文件。

后续如果需要发布到远端，先确认测试和 GPU 验收策略，再单独执行 push。不要把 `.omx/autodl-cred.json` 等凭据写入仓库或交接正文。

### 1.3 下一个 Agent 开始前必须执行

```bash
git status --short --branch
git log --oneline --decorate -8
git branch -vv
git diff main...feat/autodl-rtx5090-real-e2e --stat
```

如果工作树不是 clean，不得直接 reset/checkout 覆盖；先查看 diff，确认是否为他人未提交改动。

---

## 2. 系统结构和关键执行链路

### 2.1 服务

```text
Studio Next.js       :3000
Control API FastAPI  :8100
Runtime Gateway WS   :8101
```

主要代码：

```text
apps/studio/
apps/control-api/
apps/runtime-gateway/
runtime/orchestrator/
runtime/session/
runtime/event_bus/
runtime/recorder/
packages/protocol/
packages/sdk-python/
blocks/
profiles/
```

### 2.2 语音数字人链路

```text
Studio 麦克风
  → WebSocket Gateway
  → audio.appended
  → VAD
  → speech.detected / speech.ended
  → STT
  → transcript.completed
  → LLM
  → llm.text.delta / llm.text.done
  → TTS
  → tts.audio.delta / tts.audio.completed
  → Avatar
  → avatar.*_frame / avatar.video.ready
  → Gateway 下行
  → Studio PcmPlayer + AVMux
```

真实适配器主要包括：

- `blocks/vad/silero.py`
- `blocks/stt/sensevoice.py`
- `blocks/stt/openai_compatible.py`
- `blocks/llm/openai_compatible.py`
- `blocks/llm/ollama.py`
- `blocks/tts/voxcpm2.py`
- `blocks/tts/qwen3.py`
- `blocks/avatar/musetalk.py`
- `blocks/avatar/flashhead.py`
- `blocks/vision/openai_compatible.py`

Mock profile 可用于本地无 GPU 回归。

### 2.3 Vision 当前链路

当前实现的意图是：

```text
用户说“看看/评价/describe”
  → Orchestrator emit vision.request
  → Gateway 转发 JSON vision.request
  → Studio getUserMedia 截一帧
  → 上行 0x02 + JPEG
  → Gateway ingest_vision_frame
  → Vision Block 调用多模态 API
  → vision.result / VISION_RESULT
  → 保存最近描述
  → 后续 LLM 注入视觉描述
```

当前 Vision 代码位置：

```text
runtime/orchestrator/orchestrator.py
apps/runtime-gateway/src/avatarloom_runtime_gateway/ws_handler.py
apps/studio/hooks/use-realtime-session.ts
apps/studio/components/playground/context-bar.tsx
blocks/vision/openai_compatible.py
blocks/llm/openai_compatible.py
packages/protocol/src/avatarloom_protocol/envelope.py
```

**注意：** 目前“同一轮用户语音触发截图并等待视觉结果后再回答”的编排还没有完成。详见 `AL-P1-002`。

---

## 3. 本轮已修复的问题

### AL-P0-001：Studio JSX 语法错误

`context-bar.tsx` 的 camera button title 原来在 JSX 属性内部嵌套双引号，导致 TypeScript/esbuild 解析失败。已改为 JSX 表达式字符串。

验证：Studio TypeScript 和 Vitest 均通过。

### AL-P0-002：`captureAndSendFrame` 初始化顺序

此前 `handleMessage` 的依赖数组在 `captureAndSendFrame` 定义前引用它，存在 Temporal Dead Zone。当前提交中该函数已经位于 `handleMessage` 之前。

### AL-P0-003：RealtimeSession 接口缺少公开方法

已将以下字段加入 `RealtimeSession`：

```ts
captureAndSendFrame: () => Promise<void>;
```

### AL-P0-004：协议包漏导出 `VISION_REQUEST`

`VISION_REQUEST` 已在 `envelope.py` 定义，并补进 `avatarloom_protocol.__init__` 的 import 列表和 `__all__`。此前该遗漏会使 Orchestrator/Gateway 和 7 个测试模块在 collection 阶段直接 ImportError。

### AL-P0-005：Persona 自动加载缺少 `Path`

`runtime/orchestrator/orchestrator.py` 已补：

```py
from pathlib import Path
```

此前带 `persona_id` 的 `start_session()` 会抛 `NameError`，但被宽泛异常捕获后静默退回 profile 默认上下文。

### AL-P0-006：TTS 下行 PCM 解析偏移

Gateway 当前发送格式是：

```text
0x03 + PCM16
```

Studio 已从 offset 1 解码，并在构造 `Int16Array` 前检查剩余字节数为偶数，避免 offset 2 造成错位或 `RangeError`。

**仍未完成：** 上行 PCM 仍然是裸 PCM，和摄像头 `0x02` tag 存在歧义，见 `AL-P1-001`。下一个 Agent 不要把“下行已修复”误认为“上下行协议都已完成”。

---

## 4. 已执行验证命令和结果

### Python

```bash
uv run pytest tests/unit tests/integration
```

结果：

```text
224 passed, 2 skipped
```

跳过的是状态机对 `ERROR` 和 `CLOSED` 的预期 skip，不是失败。

### Studio TypeScript

```bash
pnpm --dir apps/studio exec tsc --noEmit
```

结果：通过。

### Studio 测试

```bash
pnpm --dir apps/studio test -- --run
```

结果：

```text
2 test files passed
10 tests passed
```

### Ruff

本轮对关键 Python 文件执行了 Ruff 检查并通过：

```bash
uv run ruff check \
  runtime/orchestrator/orchestrator.py \
  packages/protocol/src/avatarloom_protocol \
  apps/runtime-gateway/src/avatarloom_runtime_gateway/ws_handler.py
```

### 尚未执行/不能宣称通过

```text
真实 Vision API
真实浏览器摄像头权限和截图
AutoDL RTX 5090 VoxCPM2/MuseTalk/FlashHead E2E
Playwright 浏览器 E2E
完整仓库级 CI
```

---

## 5. 未完成问题清单

优先级含义：

- **P0**：阻断构建、启动或核心数据正确性；
- **P1**：能运行但功能结果可能错误、资源可能持续泄漏；
- **P2**：质量、性能、可维护性或交付缺口。

本轮 P0 已修复；下面列的是下一阶段仍需处理的问题。

### AL-P1-001：上行裸 PCM 与 `0x02` JPEG 首字节歧义

**文件：**

```text
apps/runtime-gateway/src/avatarloom_runtime_gateway/ws_handler.py
apps/studio/hooks/use-realtime-session.ts
apps/runtime-gateway/src/avatarloom_runtime_gateway/protocol.py
```

**现状：** 摄像头帧按 `0x02 + JPEG`，但麦克风发送裸 PCM。Gateway 以 `data[0] == 0x02` 判定 camera。PCM 的低字节可能自然等于 `0x02`。

**影响：** 音频块可能被误送 Vision，STT 丢块，远程 Vision 被无意触发。

**推荐修复：** 定义上行显式协议：

```text
0x00 + PCM16
0x02 + JPEG
```

前后端、协议文档和测试必须一起更新；未知 tag 应拒绝，不要继续“其他一律 PCM”。

**验收：** 构造首字节为 `0x02` 的 PCM，确认仍进入 STT；构造 `0x02 + JPEG`，确认只进入 Vision。

### AL-P1-002：Vision 与 LLM 同轮竞态

**文件：**

```text
runtime/orchestrator/orchestrator.py
blocks/llm/openai_compatible.py
```

**现状：** `transcript.completed` 同时被 LLM 订阅者和 Orchestrator 视觉触发订阅者消费。LLM 很可能在截图和 Vision API 返回前就开始回答。

**影响：** 用户说“看看我”时，第一轮回答可能没有使用刚拍的画面；视觉描述只在后续轮次注入。

**推荐修复：** 引入 `request_id` 和显式 `llm.request`：

```text
transcript.completed
  → Orchestrator 判断是否需要 Vision
  → Vision request / timeout
  → vision.result
  → llm.request（带视觉上下文）
```

Vision 超时或权限拒绝必须有降级回答路径。

### AL-P1-003：Vision context 没有 TTL 或单次消费语义

**文件：** `runtime/orchestrator/orchestrator.py`

**现状：** 仅按 `session_id` 保存最后一段描述，后续每轮 LLM 都可能继续注入旧画面。

**推荐修复：** 增加 `request_id`、时间戳和消费状态；采用单次消费或 30 秒左右 TTL，并在 session 结束时清理。

### AL-P1-004：`persona.set` 是假切换

**文件：** `apps/runtime-gateway/src/avatarloom_runtime_gateway/ws_handler.py`

**现状：** Gateway 只改 `session.persona_id`，没有加载 Persona 或调用 `orchestrator.switch_persona()`。

**影响：** LLM prompt、TTS voice ref、Avatar portrait、memory namespace 不会真正同步。

**推荐修复：** `persona.set` 先加载并校验 Persona，调用 `switch_persona()` 成功后再发送 `persona.changed`；失败时发送明确错误。

### AL-P1-005：Run 创建晚于 `transcript.completed`

**文件：**

```text
runtime/orchestrator/orchestrator.py
runtime/session/session.py
runtime/recorder/recorder.py
```

**现状：** STT 先发 transcript，Orchestrator 后处理并 `start_new_run()`。Recorder 可能在 active Run 建立前跳过 transcript，LLM/TTS 也可能拿到旧 run_id/None。

**推荐修复：** 在把本轮 transcript 交给 Recorder/LLM 前创建新 Run，并重新构造带正确 run_id 的下游事件。

### AL-P1-006：打断只 reset，不取消 LLM/TTS/Avatar 任务

**文件：**

```text
runtime/orchestrator/orchestrator.py
runtime/event_bus/bus.py
blocks/llm/openai_compatible.py
blocks/tts/
blocks/avatar/
```

**现状：** `_do_interrupt()` 调 `block.reset()`，但没有取消已经运行的 HTTP stream、TTS generator 或 Avatar render task。

**影响：** 旧回复继续消耗资源并可能与新 Run 交错下发。

**推荐修复：** Orchestrator 保存 `(session_id, run_id, category) -> asyncio.Task`，打断时 cancel/await；Block 通过 `finally` 释放底层资源并发出 interrupted 事件。

### AL-P1-007：STT 使用 `DROP_OLDEST` 会丢音频

**文件：** `runtime/orchestrator/orchestrator.py:465-479`

**现状：** STT 和 VAD 都以 `DROP_OLDEST` 订阅 `audio.appended`。STT 累积 PCM，丢一条事件就会剪掉一段语音。

**推荐修复：** STT 改用 `BLOCK` 或专用有序音频缓冲；VAD 的丢帧策略可单独保留。

### AL-P1-008：Block 实例状态没有按 session/run 隔离

**典型文件：**

```text
blocks/vad/silero.py
blocks/tts/openai_compatible.py
blocks/tts/qwen3.py
blocks/tts/voxcpm2.py
blocks/avatar/flashhead.py
blocks/stt/mock.py
blocks/llm/ollama.py
```

**典型状态：** `_h`、`_is_speaking`、`_sentence_buffers`、`_total_samples`、`_frame_index`、`_ws` 等是实例级可变状态。

**现状：** Gateway 当前每个 WebSocket 建一个 Orchestrator，暂时规避了跨连接污染，但同一 Orchestrator 的多 Session/并发 Run 仍不安全。

**架构决策：** 短期可明确限制“一 Orchestrator 一 Session”；长期应使用 `dict[(session_id, run_id), state]` 隔离。

### AL-P1-009：运行期 `BlockContext.config` 为空

**文件：** `runtime/orchestrator/orchestrator.py:538-550`

**现状：** setup 阶段有 config，process 阶段构造 `BlockContext` 时未注入实际 Block config。LLM 的 profile `systemPrompt` 等运行期读取会失效。

**推荐修复：** Orchestrator 保存 `category -> config` 并在 handler 注入，或要求所有 Block setup 时复制配置到实例字段。

### AL-P1-010：Gateway setup 失败和重复 `session.start` 的清理不完整

**文件：** `apps/runtime-gateway/src/avatarloom_runtime_gateway/ws_handler.py:170-220`

**风险：** Orchestrator 部分 setup 成功后失败时，局部已 setup 的 Block 和 Recorder 可能未清理；同一 WebSocket 重复 start 可能覆盖旧的 session/orchestrator/recorder 引用。

**推荐修复：** 已有 session 时拒绝或先 cleanup；setup 失败对局部 Orchestrator 调 `shutdown()`；Recorder 创建时机和失败回滚路径明确化。

### AL-P1-011：Vision 帧没有大小、格式和频率限制

**文件：** `apps/runtime-gateway/src/avatarloom_runtime_gateway/ws_handler.py:135-149`

**风险：** 任意大小/内容/频率的 frame 都可能触发远程 Vision API，带来内存、延迟和费用风险。

**推荐修复：** 限制最大帧大小，校验 JPEG header，加入单 session 并发锁、节流、超时和 request_id。

### AL-P2-001：Persona/Vision context 未在 session 结束时清理

**文件：** `runtime/orchestrator/orchestrator.py:232-235`

应清理：

```py
self._persona_contexts.pop(session.session_id, None)
self._vision_contexts.pop(session.session_id, None)
```

如果增加 pending Vision Future，也必须 cancel 后移除。

### AL-P2-002：VoxCPM2 `voice_ref` 与 `prompt_text` 未成对切换

**文件：**

```text
blocks/persona/loader.py
runtime/orchestrator/orchestrator.py
packages/sdk-python/src/avatarloom_sdk/base.py
blocks/tts/voxcpm2.py
```

Persona loader 有 `voice_ref_audio` 和 `voice_ref_text`，但当前只传 audio，VoxCPM2 继续使用 profile 的 `_prompt_text`。不同参考音频可能配错 prompt text，降低克隆效果。

### AL-P2-003：VoxCPM2/TTS `total_samples` 生命周期不严谨

**文件：** `blocks/tts/voxcpm2.py`、`blocks/tts/qwen3.py`、`blocks/tts/openai_compatible.py`

部分状态只在 reset/setup 清零，正常完成一个 Run 后可能累计到下一轮。需要按 Run 保存或在完成事件后正确归零。

### AL-P2-004：浏览器摄像头资源和兼容性处理不完整

**文件：** `apps/studio/hooks/use-realtime-session.ts`

后续需处理：

- 停止整个 `MediaStream` 的全部 tracks；
- `video.muted`、`playsInline`；
- `video.play()` 策略拒绝；
- metadata timeout 清理；
- canvas context 为空；
- 截图期间 WebSocket 断开；
- 按钮防重复点击。

### AL-P2-005：Studio WebSocket URL 固定 `ws://`

**文件：** `apps/studio/hooks/use-realtime-session.ts:252-263`

HTTPS 页面下需要使用 `wss://`，否则浏览器会拦截混合内容。推荐根据 `window.location.protocol` 选择协议。

### AL-P2-006：Gateway 下行队列混合不同优先级消息

**文件：** `apps/runtime-gateway/src/avatarloom_runtime_gateway/ws_handler.py`

JSON 控制事件、TTS 音频和 Avatar 帧共享一个队列。队满时旧消息可能被无差别丢弃，状态/error/response.done 也可能被丢。建议拆成控制、音频、视频队列。

### AL-P2-007：WebSocket `receive()` 没有空闲超时和心跳

**文件：** `apps/runtime-gateway/src/avatarloom_runtime_gateway/ws_handler.py:91-108`

半开连接可能永远卡在 `await self.ws.receive()`，导致 cleanup 不执行。应加 ping/pong、idle timeout 和超时后的主动清理。

### AL-P2-008：Recorder 在事件循环中同步 write/flush

**文件：** `runtime/recorder/recorder.py:120-134`

真实流式 TTS/Avatar 会产生较多事件，同步逐条 flush 会阻塞 asyncio。可改独立 writer task、批量 flush，或只记录视频元数据。

### AL-P2-009：Vision 结果在前端伪装为 assistant transcript

**文件：** `apps/studio/hooks/use-realtime-session.ts:239-247`

当前追加 `【视觉】...` 到 assistant transcript。后续应区分 tool result 与正式 assistant 回复，避免污染对话统计和历史语义。

### AL-P2-010：Vision Block 显式方法缺乏 SDK 类型契约

**文件：** `blocks/vision/openai_compatible.py`、`runtime/orchestrator/orchestrator.py`

Orchestrator 从 `dict[str, Block]` 取出对象后直接调用 `describe_frame()`，基础 Block 接口没有该方法。建议定义 VisionBlock Protocol，或把 Vision 调用改成标准事件输入/输出。

### AL-E2E-001：`scripts/e2e_real.py` 重复扫描并累计事件

**文件：** `scripts/e2e_real.py:180-226`

轮询每次从 events 列表头重新遍历，但 TTS PCM 和 Avatar frame 没有消费游标，会重复写入输出文件。验收脚本的音频长度、帧数和性能数据因此可能失真。

### AL-E2E-002：真实 GPU 验收必须记录 degradation

Profiles 配有 fallback。输出成功不等于目标真实 Block 成功。验收必须记录实际 Block ID、`degraded_blocks`、模型路径、GPU、VRAM、首 token/音频/帧时间和最终 artifact。

### AL-QA-001：没有 CI

建议最低增加 GitHub Actions：

```bash
uv run ruff check .
uv run pytest tests/unit tests/integration
pnpm --dir apps/studio exec tsc --noEmit
pnpm --dir apps/studio test -- --run
pnpm --dir apps/studio build
```

### AL-QA-002：没有浏览器 E2E

`tests/e2e/` 目前为空，Makefile 的 Playwright 目标没有形成完整测试链路。第一条 E2E 应使用 mock profile，覆盖连接、session.start、音频/文本、TTS binary、Avatar frame、response.done 和断开清理。

### AL-QA-003：Vision 协议和摄像头测试不足

需要覆盖：

- `0x00 + PCM`；
- `0x02 + JPEG`；
- 未知 tag；
- 超大 frame；
- 非 JPEG；
- Vision timeout；
- 浏览器拒绝摄像头；
- WS 断开；
- Vision context 清理/消费。

### AL-QA-004：Interruption 测试没有真正验证 HTTP cancel

现有 interruption 测试主要验证状态机。需要阻塞式 streaming mock，验证首个 delta 后 interrupt，HTTP task 被 cancel，后续旧 delta 不再出现，Run 标记为 interrupted。

### AL-P2-011：Studio Blocks Explorer 和规划中的 Block 类别未完成

`apps/studio/app/(studio)/blocks/page.tsx` 仍是 P5 stub。`blocks/memory/`、`blocks/skills/`、`blocks/transport/` 目前只有空包初始化文件。若暂不实现，应在 README 中明确标为 Planned。

---

## 6. 推荐实施顺序

### 阶段 A：协议和前端回归

1. 固定上行 `0x00 + PCM16`、`0x02 + JPEG`。
2. 为前后端增加二进制协议测试。
3. 修复 `wss`、摄像头资源释放和请求节流。
4. 通过 TypeScript、Vitest、Python tests。

### 阶段 B：Vision 同轮闭环

1. 增加 Vision `request_id`。
2. 原始 transcript 先经过 Orchestrator 决策。
3. Vision 成功/超时后再发 `llm.request`。
4. 增加单次消费或 TTL。
5. 前端区分工具结果和正式回复。

### 阶段 C：Run 与打断

1. transcript 下游前创建 Run。
2. 保存并取消 LLM/TTS/Avatar task。
3. 统一 interrupted 状态、事件和 Recorder finalize。
4. 增加真实阻塞流测试。

### 阶段 D：Block 状态模型

先决定：

- 短期强制一 Orchestrator 一 Session；或
- 长期按 `(session_id, run_id)` 隔离全部 Block 状态。

不要在两种模型之间混用隐含假设。

### 阶段 E：真实验收和交付

1. 修 `e2e_real.py` 消费游标。
2. AutoDL 复跑 `autodl-best` MuseTalk。
3. AutoDL 复跑 `autodl-flashhead` FlashHead。
4. 记录 fallback/degradation 和视频质检。
5. 建 CI 和 Playwright E2E。
6. 完成 Blocks Explorer 或明确规划边界。

---

## 7. 多 Agent 分工边界

### Agent A：协议和 Studio

```text
packages/protocol/
apps/runtime-gateway/.../protocol.py
apps/studio/hooks/use-realtime-session.ts
apps/studio/components/playground/
```

负责二进制协议、前端 Hook、摄像头 UI 和对应测试。

### Agent B：Orchestrator、Vision、Run

```text
runtime/orchestrator/
runtime/session/
runtime/event_bus/
runtime/recorder/
```

负责 Vision 同轮编排、Run ID、task cancellation、context 生命周期。不要同时让 Agent A 修改 Orchestrator。

### Agent C：Block 和 GPU

```text
blocks/
profiles/
scripts/e2e_real.py
```

负责 Block 状态隔离、VoxCPM2 prompt pair、GPU profile 和真实验收。

### Agent D：QA/CI

```text
tests/
.github/workflows/
apps/studio/playwright.config.*
```

负责回归、浏览器 E2E 和 CI。协议未冻结前不要编写大量依赖旧 tag 的测试。

### 高冲突文件

以下文件一次只应由一个 Agent 修改：

```text
runtime/orchestrator/orchestrator.py
apps/runtime-gateway/src/avatarloom_runtime_gateway/ws_handler.py
apps/studio/hooks/use-realtime-session.ts
packages/protocol/src/avatarloom_protocol/__init__.py
```

---

## 8. 复现命令速查

### 本地回归

```bash
cd /e/projects/avatarloom
uv run pytest tests/unit tests/integration
uv run ruff check runtime/orchestrator/orchestrator.py packages/protocol/src/avatarloom_protocol apps/runtime-gateway/src/avatarloom_runtime_gateway/ws_handler.py
pnpm --dir apps/studio exec tsc --noEmit
pnpm --dir apps/studio test -- --run
```

### Mock 冒烟

```bash
uv run python scripts/smoke_mock.py
```

### 本地三服务

```bash
make dev
```

默认端口：Control API `8100`、Gateway `8101`、Studio `3000`。

### AutoDL 真实 E2E

服务器环境变量和模型路径必须按实际机器调整。典型命令：

```bash
E2E_PROFILE=autodl-best E2E_TIMEOUT=300 uv run python -u scripts/e2e_real.py
E2E_PROFILE=autodl-flashhead E2E_TIMEOUT=480 uv run python -u scripts/e2e_real.py
```

真实 GPU 未运行前不要把结果写成 PASS。

---

## 9. 环境和安全注意事项

- `.omx/` 是本地 Agent 工作区，被 `.git/info/exclude` 忽略；里面可能有凭据和临时脚本，不能作为正式交付物。
- AutoDL 凭据只从本机受保护的凭据文件读取，不要复制到聊天、日志、提交或文档。
- GPU 按小时计费。下载和安装阶段尽量使用无卡实例；模型和缓存放数据盘。
- 服务器代码可能通过 tar/sftp 同步，不要默认服务器 git HEAD 与本地一致；同步后需核对文件版本。
- 后台服务启动时使用 `setsid nohup ... </dev/null >log 2>&1 &`，避免 SSH 断开时进程或管道挂住。
- 不要使用宽泛 `pkill -f` 杀进程，避免把当前命令 shell 一起杀掉。
- `workspace_root="."` 是当前既有设计，真实 Block 使用文件路径时必须核对进程 cwd；不要假定相对路径一定指向仓库根。
- 所有远程 API 调用必须考虑超时、取消、错误可见性和费用控制。

---

## 10. 给下一个 Agent 的第一句话

> 先在 `main` 上执行 `git status --short --branch && git log --oneline --decorate -8`，确认工作树干净且位于最新文档提交（代码修复基线为 `3ad4a62`）；然后先修 `AL-P1-001` 的上行二进制协议歧义，再设计 `AL-P1-002` 的 Vision 同轮等待，不要直接扩展触发词或继续堆 UI。

### 可复制的启动提示词

```text
你正在维护 E:\projects\avatarloom，当前本地 main 已包含代码修复提交 3ad4a62 及其后的交接文档提交；请以 `git log` 输出的最新提交为准。
请先执行：

  git status --short --branch
  git log --oneline --decorate -8
  git branch -vv

先阅读 docs/10-handover-maintenance-next-agent.md 和现有未提交 diff，禁止 reset/checkout 覆盖他人改动。

优先处理 AL-P1-001：把上行协议固定为 0x00 + PCM16、0x02 + JPEG，前后端同步修改并加测试；不要只改一端。
完成后再处理 AL-P1-002：Vision 触发必须等待 vision.result 或 timeout 后再让 LLM 生成同轮回答，使用 request_id 防止串请求。

每批修改后运行：
  uv run pytest tests/unit tests/integration
  pnpm --dir apps/studio exec tsc --noEmit
  pnpm --dir apps/studio test -- --run
  uv run ruff check .

最后汇报：修改文件、问题 ID、测试结果、未完成项、是否做过 AutoDL/GPU 实测、是否发生 fallback/degradation。
```
