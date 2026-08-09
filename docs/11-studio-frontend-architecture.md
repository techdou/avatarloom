# AvatarLoom Studio — 前端架构设计

> **目标读者**：改 Studio 前端的开发者。本文回答"代码该放哪、状态归谁管、数据从哪来"三个问题；视觉层的色值/圆角/间距规格见 `docs/08-studio-ui-spec.md`，本文不重复。

**版本**：v1.0 · 2026-08-06 · 基于代码实测（非静态推断）

---

## 0. 产品形态：三模式壳

Studio 不是一个页面，是三个模式的壳。三个模式心智不同，谁也不迁就谁：

| 模式 | 路由 | 服务谁 | 设计目标 |
|---|---|---|---|
| 调试台 | `/playground` | 开发者（调链路） | **可对话的调试器**——看见链路在跑，不是聊天应用 |
| 演出窗 | `/show` | 观众（演示/录屏） | 只有数字人，零调试噪音 |
| 管理台 | `/profiles` `/personas` `/avatars` `/runs` `/settings` | 配置与回看 | CRUD + 观测，克制不堆料 |

`/dashboard` `/blocks` `/sessions` 不在主导航（低频），路由保留。

---

## 1. 分层职责

```
app/                          路由层：只做数据组装，不写业务逻辑
  layout.tsx                  全局 providers（Toast）+ 主题防闪烁脚本
  (studio)/layout.tsx         AppShell（sidebar + 移动端 drawer）
  (studio)/*/page.tsx         server component，apiFetch 直连 Control API
  show/page.tsx               独立演示路由（不在 (studio) 组，无 AppShell）

components/
  ui/                         跨页共享：toast / skeleton / empty-state / error-banner / message-bubble
  layout/                     app-shell / sidebar / theme-toggle
  playground/                 调试台全部组件（playground-client / avatar-stage /
                              transcript-pane / control-bar / context-bar /
                              debug-drawer / runs-panel / pipeline-timeline / showcase-client）
  avatar/ persona/            管理台表单组件

hooks/
  use-realtime-session.ts     唯一会话状态源：WS 连接 + 音频生命周期 + 事件流收集
  use-mic-level.ts            麦克风音量采样（AnalyserNode）

lib/
  api.ts                      REST 类型 + apiFetch/apiUpload + asset URL 构造
  events.ts                   SessionEvent 类型 + 会话归约（纯函数，可单测）
  audio/                      recorder / player / sync 纯类（无 React 依赖）
```

**硬性规则**：

1. 页面组件（page.tsx）不直接持客户端状态；需要交互时委托给 `components/` 下的 client 组件。
2. `use-realtime-session` 是**唯一**与 WebSocket / 麦克风 / 扬声器通话的层。组件只消费 hook 返回值，不自己碰 `WebSocket` / `AudioContext`。
3. `lib/audio` 三个类不 import React——它们是可独立测试的纯逻辑。
4. 共享组件进 `components/ui/`；只为一个页面服务的组件留在该功能目录。

---

## 2. 数据流：两条通道

### 2.1 REST 通道（管理台）

```
page.tsx (server) ──apiFetch──> Control API :8100/api/*
client 组件      ──fetch("/api/control/*")──> Next rewrites ──> :8100
```

- server 端走绝对地址（`CONTROL_API_BASE` env，默认 `http://127.0.0.1:8100/api`）。
- client 端走相对地址 `/api/control/*`，由 `next.config.mjs` rewrites 代理。
- 两种写法都允许；server 页面优先 apiFetch（类型安全），client 组件用 fetch + 本地 state（不引入 react-query——已卸载）。

### 2.2 WebSocket 通道（调试台 / 演出窗）

```
useRealtimeSession
  ├─ 上行 JSON：session.start / session.stop / audio.interrupt / ping(20s) /
  │             vision.frame_error（截帧失败立即降级）
  ├─ 上行二进制：0x00+PCM16（麦克风，显式 tag，AL-P1-001）｜ 0x02+JPEG（摄像头截帧）
  ├─ 下行 JSON：session.started / session.state_changed / transcript.completed
  │             （含 orchestrator 重发副本 re_emitted，AL-P1-005）/ run.started /
  │             llm.text.delta / llm.text.done / tts.audio.delta(meta) /
  │             tts.audio.completed / response.done / vision.request / vision.result /
  │             avatar.video.ready / persona.changed / error / pong
  └─ 下行二进制：0x03+PCM16（TTS 音频）｜ 0x01+subtag+JPEG（Avatar 帧，subtag 0x01=speech）
```

- 音频是**主时钟**：`PcmPlayer` 用 `AudioContext.currentTime` 调度，`AVMux` 按音频播放位置消费视频帧（对齐 VoxEMW，见 docs/02）。
- WS URL 推导优先级：`?wsPort=` 参数 > `NEXT_PUBLIC_WS_PORT` env > 隧道映射（页面端口 13000 → gateway 18101）> 默认 8101；https 页面自动 `wss://`（AL-P2-005）。隧道端口约定见 README「端口约定」（用户入口永远是 13000/18100/18101）。
- 下行通道（Gateway 侧，AL-P2-006）：control/audio/video 三队列，控制不丢、媒体丢最旧；心跳 20s ping + gateway 90s idle 断开（AL-P2-007）。
- 帧构造纯函数在 `lib/frames.ts`（`buildPcmUplinkFrame` / `buildCameraUplinkFrame`，配协议单测）。

---

## 3. 状态模型（use-realtime-session）

### 3.1 分组原则

按联动强度分四组，不做"全塞一个 reducer"的过度统一：

| 组 | 状态 | 容器 | 理由 |
|---|---|---|---|
| 连接 | `conn` `error` | useState | 生命周期独立，重置逻辑简单 |
| 会话运行时 | `sessionState` `sessionId` `currentRunId` `timing` `events` | useReducer | 联动强：session.started 全重置、run.started 开新窗口、response.done 封口 |
| 对话内容 | `transcript` `llmDelta` | useState | 纯追加型，无联动 |
| 渲染高频 | `frameUrl` `debugInfo` | useState | 每秒 ~25 次更新，不进 reducer 避免放大渲染 |

### 3.2 事件流（SessionEvent）

调试面板的全部数据来自前端自己收集，不依赖后端改动：

```ts
interface SessionEvent {
  type: string;        // "transcript.completed" 等
  ts: number;          // 本地接收时刻（ms）
  runId: string | null;
  summary: string;     // payload 摘要（截断 60 字）
}
```

- `handleMessage` 每收一个下行 JSON 事件压入 ring buffer（上限 200 条）。
- `run.started` 开启当前 run 窗口；`response.done` / `response.interrupted` 封口。
- 里程碑延迟（首字/首音/首帧）从 events 实时计算，与 DebugDrawer 的 timing 展示共用一份数据。

归约逻辑放在 `lib/events.ts`（纯函数），hook 只负责调用——事件归约可脱离 React 单测。

### 3.3 不归 hook 管的状态

- profile/persona 选择：PlaygroundClient 持有 + localStorage 持久化（key: `al.profile` / `al.persona`）。
- UI 开关（debug 抽屉、runs 面板）：各组件本地 useState。
- 主题：`<html>` class + localStorage（`theme`），layout.tsx 内联脚本防闪烁。

---

## 4. 设计令牌体系

### 4.1 颜色（16 token，亮暗双值）

亮色系在 `tailwind.config.ts`；暗色通过 `dark:` 变体逐处声明。**禁止**在组件里写 `dark:xx-[#...]` 任意值——暗色值只能来自 token 组（bg-subtle / fg / fg-muted / border / accent / ok / warn / err / info）。

新增：`info`（#0891b2）、`border.strong`（#d4d4d8）。

### 4.2 字号（7 阶）

| 用途 | 类 | px |
|---|---|---|
| 页面标题 | `text-2xl` | 24 |
| 卡片标题 | `text-lg` | 18 |
| 大正文 | `text-base` | 16 |
| 正文（默认） | `text-sm` | 14 |
| 次要说明 | `text-xs` | 12 |
| 元信息/标签 | `text-micro` | 11 |
| 调试数字 | `text-micro font-mono` | 11 |

**禁止** `text-[10px]`（已全部清除）；任意值字号禁止新增。

### 4.3 间距 / 圆角 / 阴影 / 动效

- 间距：Tailwind 默认 8pt 刻度（1/2/3/4/6/8），禁止 `gap-1.5` `p-2.5` 等非标。
- 圆角：`rounded`（4，badge）/ `rounded-lg`（8，input/btn/气泡）/ `rounded-xl`（12，card）/ `rounded-full`（头像、状态点）。禁止 `rounded-2xl+`。
- 阴影：`shadow-card`（默认卡）/ `shadow-pop`（抽屉、toast、hover 卡）/ `shadow-accent`（仅 sidebar logo）。按钮不带阴影。
- 动效：`duration-quick`（120ms，hover/focus）/ `duration-default`（200ms，卡片、toast）/ `duration-slow`（400ms，抽屉、模态）。`prefers-reduced-motion` 全局守卫。

---

## 5. 组件契约（跨页共享）

| 组件 | Props | 用途 |
|---|---|---|
| `EmptyState` | `icon? title description? action? variant?` | 全站空态，6+ 页面复用 |
| `ErrorBanner` | `error hint? onRetry?` | 全站错误提示（err 色系） |
| `MessageBubble` | `role text label? streaming?` | 聊天气泡——Playground 与 runs/[id] 同一实现 |
| `Toast` | （已有） | 4s TTL，不动 |
| `Skeleton` | （已有） | loading.tsx 复用 |

页面级结构约定：每个管理页以 `page-header`（`page-title` + 可选 `page-desc`）开头；区块标题用 `section-label`。

Playground 内部组件边界：

```
PlaygroundClient          orchestration only（状态接线，无视觉细节）
├─ ContextBar             连接状态 + profile/persona 选择 + 调试/主题开关 + 演示链接
├─ AvatarStage            数字人画面（frame / WelcomePane / PendingAvatar）
├─ TranscriptPane         对话区（MessageBubble 列表 + llmDelta 流式气泡）
├─ ControlBar             麦克风 / 打断 / 音量波形 / 调试数字
└─ DebugDrawer            调试面板（见 §6）
```

---

## 6. 调试面板（DebugDrawer v2）

调试台区别于聊天产品的核心。数据 100% 来自 §3.2 事件流。

- **收起态**：一行——当前 run 的阶段进度点（聆听 → 识别 → 思考 → 回复 → 演出），已完成阶段实心点。
- **展开态**（两栏）：
  - 左栏「事件流」：当前 run 的实时事件列表，mono 字体，`+ms 相对时间 + 事件名 + 摘要`，terminal 风格（克制单色，仅错误用 err 色）。
  - 右栏「里程碑」：首字 / 首音 / 首帧 / 总时长实时延迟（transcript 完成时刻为 t0）；「水位」：帧数 / 音频块 / 帧队列长度。

历史 run 的静态时序仍由 `PipelineTimeline`（runs/[id]、RunsPanel 复用）承担——实时与历史是两种数据形态，组件不强行合并。

---

## 7. 演出窗（/show）

- 无 AppShell、autoConnect、全屏 cover 画面、顶部细状态条、底部字幕条、悬浮麦克风按钮。
- 连接失败自动重试（指数退避 3 次），断连状态明示但不打断画面。
- Playground ContextBar 提供「复制演示链接」：`/show?persona=x&profile=y`，手机扫码即开。
- **克制原则**：此路由只许减东西，不许加调试 UI。

---

## 8. 与其他文档的关系

| 文档 | 关系 |
|---|---|
| `docs/08-studio-ui-spec.md` | 视觉规格（色值/组件状态/逐页清单）。本文生效后，08 的 P0 批（令牌收尾、EmptyState/ErrorBanner、page-header 统一）视为已实施；P1-1 状态机重构以本文 §3 为准（分组而非全量 useReducer）。 |
| `docs/02-事件协议状态机与音画同步.md` | WS 协议与音画同步的权威定义（含浏览器↔Gateway 通道协议章节，AL-P1-001 后已补录），本文 §2.2 是它的前端投影。 |
| `docs/10-handover-maintenance-next-agent.md` | 已同步：上行 PCM 加了 0x00 tag（AL-P1-001 已修）；vision 结果区分工具消息与正式回复（AL-P1-002）待同步。 |

---

## 9. 演进方向（本轮不做，仅记录）

- 暗色 token 全 CSS 变量化（一处改色全局生效）
- Persona 装配详情页（personas/[id]，依赖 control-api 绑定关系 API）
- Blocks Explorer（可视化模块浏览；拖拽编排明确不做）
- i18n（当前全中文 UI）

---

## 10. 实施记录（2026-08-06）

| 批次 | 内容 | 提交 |
|---|---|---|
| 0 | 本文档 | `8a514d0` |
| 1 | 令牌收尾（info/border.strong/fontSize.micro/duration）+ 11 处 dark hex token 化 + 32 处任意字号统一 + EmptyState/ErrorBanner/MessageBubble + 卸载 react-query + page-header 统一 | `92880cf` |
| 2 | lib/events.ts 归约（11 单测）+ hook 状态分组 + 补接 run.started 等 4 个下行事件（commit 含并行协议修复：0x00 PCM tag / wss / vision.frame_error） | `b988668` |
| 3 | playground-client 迁移拆分（4 个纯展示组件）+ DebugDrawer v2（阶段进度点 + 实时事件流 + 里程碑） | `87aad07` |
| 4 | settings 当前活动卡、YAML 迁移、personas/avatars/profiles/dashboard 视觉、runs/[id] MessageBubble 复用 | `cf9777f` |
| 5 | /show 断线自动重试 + ContextBar 复制演示链接（clipboard 降级） | `e304b33` |
| 6 | recorder.getLevel() + 音量波形条 + WS 非主动断线自动重连 + 空格切麦 | `c76bde3` |
| 7（2026-08-09） | showcase 重试层删除（统一归 hook 逻辑）+ 展示组件 React.memo 优化重渲染 | — |

每批次门禁均通过：`tsc --noEmit`、`vitest --run`（21 项）、`next build`。
