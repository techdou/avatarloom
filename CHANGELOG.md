# Changelog

## v0.2.0 — 2026-08-07

**Studio 前端架构与 UI/UX**（8 commits）

- 前端架构文档 `docs/11`：三模式壳（Playground 调试台 / /show 演出窗 / 管理台）、分层职责、四组状态模型。
- 设计令牌收尾：info/border.strong/fontSize.micro/动效 token；暗色值全 token 化（修暗色卡片误渲染浅色的 bug）；32 处任意字号清零。
- 共享组件：EmptyState / ErrorBanner / MessageBubble（含 tool 变体）；卸载零使用的 react-query。
- `lib/events.ts` 纯函数会话归约 + hook 状态分组重构；DebugDrawer v2：阶段进度点 + 本轮实时事件流 + 里程碑延迟。
- Playground 拆分 orchestration + 4 纯展示组件；/show 断线自动重试；演示链接复制；音量波形条；WS 断线自动重连；空格切麦。

**协议与同轮视觉**（c08feab + 本轮）

- 上行二进制显式协议：`0x00+PCM16` / `0x02+JPEG`，未知 tag 拒绝（AL-P1-001）；docs/02 补录通道协议章节。
- Vision 同轮编排：触发词 → 截帧 → 多模态分析 → LLM 同轮注入（AL-P1-002）；context 单次消费 + 30s TTL（AL-P1-003）；帧大小/SOI 校验 + 并发锁 + 节流（AL-P1-011）。
- 前端 `wss://` 自适应（AL-P2-005）；`vision.frame_error` 截帧失败立即降级。

**Run / 打断 / 通道健壮性**（本轮）

- AL-P1-005：orchestrator 以新 run_id 重发 transcript.completed（sink-only 副本，防 bus 反馈循环），Recorder 落录用户文本。
- AL-P1-006：协作式打断取消——LLM 关闭 HTTP 流并标记 interrupted、TTS 丢弃 cancelled 输出、MuseTalk 按 session 取消渲染 task。
- AL-P2-003：TTS 计数/缓冲按 run 隔离，不再跨轮累计。
- AL-P2-006：Gateway 下行 control/audio/video 三队列——控制不丢、媒体丢最旧、慢客户端不反压。
- AL-P2-007：前端 20s ping + Gateway 90s idle 断开半开连接。
- AL-P1-004：`persona.set` 真切换（调 `switch_persona()`）。
- AL-P2-009：vision.result 前端独立工具消息样式，不再伪装 persona 回复。

**E2E 验收基础设施**（本轮）

- AL-E2E-001：`e2e_real.py` 消费游标——TTS PCM/帧不再重复累计，验收数据可信。
- AL-E2E-002：manifest 记录 ready_blocks / degraded_blocks / 首事件延迟 / 事件分布 / GPU 快照——fallback 不再静默。
- fallback 链递归 visited 防护（自指/成环快速失败，不再无限递归）。
- `E2E_OUT_DIR` env 覆盖；mock/static avatar 跳过 mp4 等待。

**测试**：237 pytest + 28 vitest 全绿（新增协作式取消、re-emit、帧协议共 11 项）。

## v0.1.0 — 2026-08-05

- 确立 AvatarLoom / 灵构项目名称。
- 定义 Composable Digital Human Runtime 定位。
- 完成模块化数字人总体架构。
- 定义 Block SDK、Manifest、事件协议和显式状态机。
- 定义 Audio Clock、Idle/Speech Frame 和音画同步机制。
- 设计 AvatarLoom Studio、Control Plane、Run Recorder 和 Artifact Writer。
- 提供 Lite 12GB、Distributed、Full 24GB+ 三类 Runtime Profile。
- 提供完整项目开发 Prompt 和分阶段 Prompt。
