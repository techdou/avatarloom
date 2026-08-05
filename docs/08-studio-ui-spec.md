# AvatarLoom Studio — UI/UX 优化规格

> **目标读者**:下一位接手改 Studio 前端的开发者。拿到这份文档,应当能直接照着改设计令牌、组件、页面,不再猜。
>
> **设计原则(本项目硬约束)**
> 1. **专业工具感**,不是 SaaS landing page。**禁止**装饰性大渐变、emoji 徽章、eyebrow+title+desc 三层堆砌、过度对称网格。
> 2. **反 AI-slop**——具体清单见第 5 节。
> 3. **真实优先**——空状态不画"假人脸",不编"10,000+ users"假数据。所有装饰都要回答"这传达了什么信息"。

---

## 0. 目录

- [1. 当前状态诊断(读代码结论)](#1-当前状态诊断读代码结论)
- [2. 设计令牌(Design Tokens)](#2-设计令牌design-tokens)
- [3. 组件视觉契约(Visual Contract)](#3-组件视觉契约visual-contract)
- [4. 逐页改造清单](#4-逐页改造清单)
- [5. 反 AI-slop 检查清单](#5-反-ai-slop-检查清单)
- [6. 架构与代码层问题](#6-架构与代码层问题)
- [7. 优先级排序与投入产出](#7-优先级排序与投入产出)
- [8. 实施注意事项](#8-实施注意事项)

---

## 1. 当前状态诊断(读代码结论)

**技术栈确认**(引证 `apps/studio/package.json`):
- Next.js 14.2 App Router + TypeScript 5.6
- Tailwind 3.4(`tailwind.config.ts` 自定义 token)
- lucide-react(图标)+ clsx(条件 class)
- @tanstack/react-query 5.59(**装了但未使用**)
- 无 UI 库(自研),无 next-themes(自研 `ThemeToggle`)

**整体调性定调**:
> **「已具备专业工具骨架,但有几处明显 AI 残留与硬编码泄漏」**——配色克制、token 体系雏形已立、组件边界清晰;主要问题在 **暗色 hex 散落**、**WebSocket 配置硬编码**、**Playground 立绘占位用 SVG 画脸**、**react-query 装了不用**。

### 1.1 视觉层(七维扫描,基于代码推断)

| 维度 | 现状(证据) | 评级 |
|---|---|---|
| 调性 | 白底黑字 + 单一靛蓝主色,中性灰 | ✓ 克制专业 |
| 视觉权重 | 标题 `text-2xl` 统一,正文字号 `text-sm` 统一 | ✓ 一致 |
| 节奏 | 4/8 基线间距,`gap-4` / `space-y-2.5` 主导 | ✓ 韵律 |
| 色彩 | `#4f46e5` 靛蓝(非 `#3B82F6` AI 蓝)— 避开了 A1 | ✓ 避坑 |
| 一致性 | card / btn / input / badge 四个基础组件类复用,跨页一致 | ✓ 强 |
| 可访问性 | 字色有 `fg-muted / fg-subtle` 梯度;焦点环 `focus:ring-accent` | △ 主色对比度待测 |
| 品牌契合 | "灵构 Studio" + 副标"模块化数字人运行平台" | ✓ 调性符合工具 |

### 1.2 架构层(六层审计)

| 层 | 现状 | 问题 | 证据 |
|---|---|---|---|
| **设计令牌** | tailwind config 已有 `bg/fg/border/accent/ok/warn/err` 6 组 | 暗色 hex 散落 7+ 处:`#131318`、`#ededf2`、`#0a0a0c` | `sidebar.tsx:52`, `runs/[id]/page.tsx:207,250,295`, `playground-client.tsx:457,477` |
| **组件层** | 4 个基础类(btn/card/input/badge)+ sidebar/app-shell/playground-client/asset-uploader | 无独立 Button/Card/Input 组件类,直接用 `@apply` 工具类 — 主题切换灵活但组合受限 | `globals.css:31-86` |
| **布局层** | App Router + 固定 `max-w-7xl` 容器 + 移动端 drawer | 移动端断点 `md` (768) 单一,缺少 `sm/md/lg/xl` 系统性断点 | `app-shell.tsx:48` |
| **主题层** | 自研 dark/light toggle,localStorage + media query 兜底 | 暗色 token 不是 CSS 变量,直接写 `dark:bg-[#xxx]` — 改主题要全局扫 | `tailwind.config.ts:11-26` + 多处 `dark:` |
| **页面层** | 9 个页面,均 server component + 顶部 page-header | 部分页缺 page-header(runs/blocks/sessions)只有裸 `<h1>` | `runs/page.tsx:15` 等 |
| **状态层** | loading.tsx 5 个(skeleton 匹配布局) | error 状态:各页 `try/catch` 重复实现 6 次;**无统一 EmptyState 组件** | `runs/page.tsx:16-18` 等 |

### 1.3 信息架构判断(用户旅程)

**目标用户**:研二学生豆哥,需要快速"调通一次对话"。

| 步骤 | 当前路径 | 步数 | 体验 |
|---|---|---|---|
| 1. 进入 | `/` → 重定向 `/dashboard` | 0 | ✓ 干净 |
| 2. 看总览 | dashboard 3 stat cards + 快速开始 4 步列表 | 1 | ✓ 引导清晰 |
| 3. 选配置 | 点击"选择运行时配置"→ `/profiles`,硬编码 `autodl-best` badge 标记"推荐" | 2 | △ 用户不能改,得改 `playground-client.tsx:103` 的 `profile_id` 字符串 |
| 4. 开对话 | `/playground` → 点击"连接并开始" → 浏览器弹麦克风权限 → 开始说话 | 3 | △ WebSocket URL `ws://${hostname}:8101` 硬编码,无法配 |
| 5. 看记录 | `/runs` 列表 → 点击进 detail | 4 | ✓ 清晰 |

**问题**:**步骤 3 的 `profile_id` 选择是隐藏的**——用户必须改源码才能切换 persona+profile 组合。这是一个产品功能问题,但 UI 层要先把"profile 选择"组件化,让"切换运行时配置"不只是一个文字。

---

## 2. 设计令牌(Design Tokens)

> **现状**:`tailwind.config.ts:11-35` 已建立 `bg/fg/border/accent/ok/warn/err` + 3 个 boxShadow。**要做的是收敛 + 暗色 token 化 + 补动效时长**。

### 2.1 颜色(主推,16 个 Token)

**保留的现状值**(全部进 token 变量,不再硬编码):

| Token 名 | 亮色 | 暗色 | 用途 | 替代品/备注 |
|---|---|---|---|---|
| `bg` | `#ffffff` | `#0a0a0c` | 主背景 | 已是 `bg-bg` |
| `bg-subtle` | `#fafafa` | `#131318` | 次背景(sidebar/输入框) | 暗色 **必须** 加 token,不再写 `dark:bg-[#131318]` |
| `fg` | `#0a0a0a` | `#ededf2` | 主文字 | 暗色 **必须** 加 token |
| `fg-muted` | `#666666` | `#a1a1aa` | 次文字(标签/说明) | |
| `fg-subtle` | `#999999` | `#71717a` | 弱文字(placeholder/元信息) | |
| `border` | `#e5e5e5` | `#27272a` | 默认边框 | |
| `accent` | `#4f46e5` | `#6366f1` | 主色(靛蓝) | 已是 `accent.DEFAULT` |
| `accent-hover` | `#4338ca` | `#4f46e5` | 主色 hover | 已有 |
| `accent-soft` | `#eef2ff` | `rgba(99,102,241,0.15)` | 主色软底 | 暗色不要写 `dark:bg-accent/15`,要 token |
| `accent-ring` | `rgba(79,70,229,0.35)` | `rgba(99,102,241,0.4)` | 焦点环 | 已有 |
| `ok` | `#16a34a` | `#22c55e` | 成功 | 已有 |
| `warn` | `#d97706` | `#eab308` | 警告 | 已有 |
| `err` | `#dc2626` | `#ef4444` | 错误 | 已有 |
| `info` | `#0891b2` | `#06b6d4` | 信息(新加) | **当前缺**,toast info 用 `accent` 是混淆,加新 token |
| `code-bg` | `#f5f5f5` | `#1e1e22` | code/inline | **新加**,settings 页 `code` 元素用 |

**Tailwind config 重构建议**(引证 `tailwind.config.ts:11-26`):

```ts
// apps/studio/tailwind.config.ts(改)
colors: {
  bg: { DEFAULT: "#ffffff", subtle: "#fafafa" },
  fg: { DEFAULT: "#0a0a0a", muted: "#666666", subtle: "#999999" },
  border: { DEFAULT: "#e5e5e5", strong: "#d4d4d8" },  // 新加 strong(深一档)
  accent: {
    DEFAULT: "#4f46e5",
    hover: "#4338ca",
    soft: "#eef2ff",
    ring: "rgba(79, 70, 229, 0.35)",
  },
  ok:    { DEFAULT: "#16a34a", soft: "#dcfce7" },  // 新加 soft(成功背景)
  warn:  { DEFAULT: "#d97706", soft: "#fef3c7" },
  err:   { DEFAULT: "#dc2626", soft: "#fee2e2" },
  info:  { DEFAULT: "#0891b2", soft: "#cffafe" },  // 新加
  code:  { DEFAULT: "#f5f5f5", border: "#e5e5e5" },
},
```

**暗色 token 通过 `dark:` 变体**——但所有暗色都进 Tailwind,不再写 `dark:bg-[#xxx]`。具体方法:在 `globals.css` 的 `@layer base` 改写 `html.dark` 下的 token。

**`globals.css` 改造**(引证 `app/globals.css:18-29`):

```css
@layer base {
  html { @apply bg-bg text-fg antialiased; }
  html.dark { @apply bg-[#0a0a0c] text-[#ededf2]; }
  body { @apply min-h-screen; }
  h1 { @apply text-2xl font-semibold tracking-tight; }
  h2 { @apply text-lg font-semibold tracking-tight; }
  h3 { @apply text-base font-medium; }
}
```

**扫干净所有 `dark:bg-[#xxx]` / `dark:text-[#xxx]`**:
- `playground-client.tsx:277` `dark:bg-[#131318]` → `dark:bg-bg-subtle`
- `playground-client.tsx:457,477` `dark:text-[#ededf2]` → `dark:text-fg`
- `runs/[id]/page.tsx:207,250,295` 同样改
- `sidebar.tsx:52` `dark:bg-[#131318]` → `dark:bg-bg-subtle`

### 2.2 字号(7 阶,克制不堆砌)

**现状问题**:`globals.css` 只设了 h1/h2/h3,正文 `text-sm`(14px)— 实际产线最低应 14px(合格)。但出现了大量 `text-[10px] / text-[11px] / text-[12px] / text-[14px] / text-[16px]` 散落——31 处。

**Token 化方案**(写进 `tailwind.config.ts` `fontSize`):

| 名称 | px / line-height | Tailwind 类 | 用途 |
|---|---|---|---|
| `display` | 32 / 40 | `text-2xl` (保留) | 极少用,Hero/大数字 |
| `title` | 24 / 32 | `text-2xl` (page-title 复用) | 页面标题 |
| `subtitle` | 18 / 28 | `text-lg` | 卡片标题 |
| `body-lg` | 16 / 24 | `text-base` | 大正文(很少) |
| `body` | 14 / 20 | `text-sm` | **默认正文** |
| `caption` | 12 / 16 | `text-xs` | 次要说明 |
| `micro` | 11 / 14 | `text-[11px]` | 标签/元信息(token 化) |

**删掉所有 `text-[10px]`**(目前 8 处)→ 统一用 `text-[11px]` token 类。

**新增 utility class**:
```css
@layer components {
  .text-meta { @apply text-[11px] tracking-tight; }  /* 通用元信息 */
}
```

### 2.3 间距(8pt 基线)

**现状**:`gap-2/3/4` 主导,有 118 处 `p-[n]/gap-[n]/py-[n]/px-[n]` 任意值。

**Token 方案**(只用 Tailwind 默认 8pt 刻度,不要再写 `gap-3.5` `p-2.5` 这类非 8 倍数):

| Tailwind | px | 用途 |
|---|---|---|
| `gap-1` / `p-1` | 4 | 极紧(icon + 文字) |
| `gap-2` / `p-2` | 8 | 紧凑(列表项) |
| `gap-3` / `p-3` | 12 | 卡片内(允许一次) |
| `gap-4` / `p-4` | 16 | 卡片标准 |
| `gap-6` / `p-6` | 24 | 区块间距 |
| `gap-8` | 32 | 页面级大间距 |

**清理建议**:
- `p-3.5` `px-3.5` `py-2.5` `gap-2.5` `gap-1.5` → 替换为标准 8pt(`p-3` `px-3` `py-2` `gap-2` `gap-1`)。极个别需要 12px 紧凑度的,允许 `p-3`(已经 12px)。

### 2.4 圆角(3 阶)

| Token | px | 用途 | Tailwind |
|---|---|---|---|
| `radius-sm` | 4 | badge、icon button | `rounded` |
| `radius-md` | 8 | input、card、button | `rounded-lg` |
| `radius-lg` | 12 | 大卡片、modal | `rounded-xl` |
| `radius-pill` | 9999 | 头像、tag | `rounded-full` |

**特殊**(playground 头像、状态点):允许 `rounded-full`。

**禁止**:`rounded-2xl`(太大了,像 AI slop)、`rounded-3xl`(完全 slop)。

### 2.5 阴影(2 阶,克制)

**现状 3 个**:`shadow-card`(微)、`shadow-pop`(中)、`shadow-accent`(品牌)— `shadow-accent` **只用在主按钮 + sidebar logo**(已经有,合理)。

**规则**:
- 默认 card:有 `shadow-card`
- hover card:加 `shadow-pop`
- 按钮:不加 shadow(只边框 + 背景)
- **toast**:`shadow-pop` ✓ 已有
- 抽屉:`shadow-pop` ✓ 已有
- 头像占位:`shadow-card` ✓ 已有
- 气泡:`shadow-card` ✓(playground-client.tsx:355)

**禁止**:`shadow-xl / shadow-2xl`、每张卡片都加 `shadow-lg`(AI slop C8)。

### 2.6 动效(3 阶,新增)

| 名称 | 时长 | 缓动 | 用途 |
|---|---|---|---|
| `ease-quick` | 120ms | `cubic-bezier(0.4, 0, 0.2, 1)` | hover、focus 反馈 |
| `ease-default` | 200ms | 同上 | 卡片进入、toast 弹入 |
| `ease-slow` | 400ms | `cubic-bezier(0.16, 1, 0.3, 1)` | 抽屉滑入、模态 |

**新增 Tailwind extend**:
```ts
transitionDuration: { quick: "120ms", default: "200ms", slow: "400ms" },
```

**`globals.css` 增加 reduced-motion 守卫**:
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## 3. 组件视觉契约(Visual Contract)

> 4 个基础类已在 `globals.css` 定义(btn / card / input / badge)。本节给出**精确状态规格**,作为实现参照。

### 3.1 Button(`.btn`)

| 变体 | 背景 | 边框 | 文字 | Hover | Active | Disabled | 焦点环 |
|---|---|---|---|---|---|---|---|
| `btn`(默认) | `bg-white` | `border-border` | `text-fg` | `bg-bg-subtle border-fg/20` | `scale-[0.98]` | `opacity-50 pointer-events-none` | `focus-visible:ring-2 focus-visible:ring-accent-ring` |
| `btn-primary` | `bg-accent` | `border-accent` | `text-white` | `bg-accent-hover` | `scale-[0.98]` | 同上 | 同上 |
| `btn-ghost` | `transparent` | `transparent` | `text-fg` | `bg-border/40` | 同上 | 同上 | 同上 |
| `btn-danger` | `bg-white` | `border-err/30` | `text-err` | `bg-err/5` | 同上 | 同上 | 同上 |

**尺寸**:
- `btn-sm`: `px-2.5 py-1.5 text-xs rounded-md` ✓ 已有
- `btn`(默认): `px-3.5 py-2 text-sm rounded-lg`
- `btn-lg`(**新加**): `px-5 py-2.5 text-base rounded-lg` — 用在 Playground "连接并开始" 之类主操作

**Loading 态**(btn-primary 专属):保留宽度,文字替换为 `Loader2` 16px spinner + 文字。**不要**整个按钮变成 spinner。

### 3.2 Card(`.card`)

| 状态 | 边框 | 背景 | 阴影 | 圆角 | 内边距 |
|---|---|---|---|---|---|
| 默认 | `border-border` | `bg-white` | `shadow-card` | `rounded-xl` | `p-4` |
| Hover(可点击) | `border-accent/40` | `bg-white` | `shadow-pop` | 同上 | 同上 |
| 选中 | `border-accent` `ring-1 ring-accent/20` | `bg-accent-soft` | `shadow-card` | 同上 | 同上 |

**暗色**:`bg-bg-subtle` + `shadow-none`(阴影在暗色几乎不可见,关闭)。

**变体**:
- `card p-0`:用于 Avatars 列表(`p-0` 后内部用 `aspect-[4/3]`)
- `card flat`:无 shadow(表格行)

### 3.3 Input(`.input`)

| 状态 | 边框 | 背景 | 文字 | 焦点 |
|---|---|---|---|---|
| 默认 | `border-border` | `bg-white` | `text-fg` | `ring-2 ring-accent-ring border-accent` |
| Error | `border-err` | `bg-white` | `text-fg` | `ring-2 ring-err/30` |
| Disabled | `border-border` | `bg-bg-subtle` | `text-fg-subtle` | — |

**结构约定**:`<label>` 写在 input 上方,块级,`text-sm mb-1`。错误提示用 `<p className="text-xs text-err mt-1">`,不直接放 input 旁边。

### 3.4 Badge(`.badge`)

| 变体 | 边框 | 背景 | 文字 |
|---|---|---|---|
| `badge`(默认) | `border-border` | `bg-bg-subtle` | `text-fg` |
| `badge-accent` | `border-accent/30` | `bg-accent/5` | `text-accent` |
| `badge-ok` | `border-ok/30` | `bg-ok/5` | `text-ok` |
| `badge-warn` | `border-warn/30` | `bg-warn/5` | `text-warn` |
| `badge-err` | `border-err/30` | `bg-err/5` | `text-err` |
| `badge-info`(**新加**) | `border-info/30` | `bg-info/5` | `text-info` |

**禁止**:在 badge 上加 emoji(`🚀⚡️✨🎯💡` 等)— 项目硬约束。`"推荐"` `"已设置"` 等用纯中文文字 + icon(`CheckCircle2`)即可。

### 3.5 ConnectionState(Playground 顶部条)— 新组件

**位置**:`apps/studio/components/playground/connection-bar.tsx`(从 `playground-client.tsx` 抽离)

| 状态 | 圆点 | 文案 | 右侧按钮 |
|---|---|---|---|
| `disconnected` | `bg-fg-subtle` | "未连接" | `btn-primary` "连接" |
| `connecting` | `bg-warn animate-pulse` | "连接中…" | `btn` disabled "连接中…" |
| `connected` | `bg-ok` | "已连接 Runtime Gateway" | `btn-danger` "断开" |
| `error` | `bg-err` | "连接失败" | `btn-primary` "重试" |

**Props 契约**:
```ts
interface ConnectionBarProps {
  conn: "disconnected" | "connecting" | "connected" | "error";
  profile: { id: string; name: string; modules: string };  // 显示在副标
  onConnect: () => void;
  onDisconnect: () => void;
}
```

### 3.6 EmptyState(新组件,跨页复用)

> **动机**:当前 6 个页面(avatars/personas/blocks/runs/sessions/profiles)各自写"暂无 X"提示 — 不一致。

**Props 契约**:
```ts
interface EmptyStateProps {
  icon?: React.ReactNode;       // lucide 图标(不要 emoji)
  title: string;                // 一句话,不超 12 字
  description?: string;         // 可选解释
  action?: { label: string; href?: string; onClick?: () => void };
  variant?: "card" | "bare";    // card = 居中卡片;bare = 轻提示
}
```

**视觉**:
- icon: 40×40 圆角方块,`bg-bg-subtle text-fg-muted`,**不要** 用 `bg-accent-soft text-accent`(避免"红色+绿色+蓝色 一起"的 slop)
- title: `text-base font-medium`
- description: `text-sm text-fg-muted max-w-md`
- action: `btn-primary`(主操作)/ `btn`(次操作)

**禁止**:
- 不画装饰性 SVG(典型 slop 标志,如 abstract circles)
- 不写"看起来你还没有 X?那就创建吧!"——保持陈述句

### 3.7 ErrorBanner(新组件,统一各页错误提示)

```ts
interface ErrorBannerProps {
  error: string;
  hint?: string;            // "请确认 control-api 服务已启动(默认端口 8100)"
  onRetry?: () => void;
}
```

**视觉**:`rounded-lg border border-err/30 bg-err/5 px-4 py-3 text-sm text-err`
- 文案:简短错误 + 可选 hint
- 右侧:可选 "重试" 按钮(若传 `onRetry`)

**应用到**:`runs/page.tsx:16-18` `avatars/page.tsx:26-30` `personas/page.tsx:23-27` `blocks/page.tsx:23-27` `sessions/page.tsx:15-17` `profiles/page.tsx:24-28` — 6 处替换。

---

## 4. 逐页改造清单

> 每条包含:**问题 → 证据 → 改造 → 为什么**。

### 4.1 根布局 / Shell

#### `/app/layout.tsx`
- **不动**。结构清晰(theme 闪烁守卫 + 三层 Provider),无问题。

#### `/components/layout/app-shell.tsx`
- **问题 1**:抽屉 overlay `bg-black/40 backdrop-blur-[1px]` 用了 backdrop-blur — 移动端低端机卡顿。
  - **证据**:`app-shell.tsx:56`
  - **改造**:删 `backdrop-blur-[1px]`,只留 `bg-black/40`。
  - **为什么**:专业工具追求响应感,blur 是装饰性负担。
- **问题 2**:移动端顶栏 14px 高 + 9×9 menu 按钮,触控目标可能 < 44px。
  - **证据**:`app-shell.tsx:81` `w-9 h-9`
  - **改造**:`w-10 h-10`(40×40,接近 a11y 下限)。
  - **为什么**:数字人 demo 场景用手机访问是合理路径。
- **问题 3**:顶栏 AvatarLoom 文字 + ThemeToggle 紧贴,缺视觉呼吸。
  - **证据**:`app-shell.tsx:75-87`
  - **改造**:左 logo + 中间空 flex-1 + 右 ThemeToggle(平衡布局)。

#### `/components/layout/sidebar.tsx`
- **问题 1**:底部"AutoDL RTX 5090 · v0.2.0"硬编码 + 顶 logo 副标"灵构 Studio"。
  - **证据**:`sidebar.tsx:63, 98`
  - **改造**:把版本号从 `package.json` 通过 env 读(`process.env.NEXT_PUBLIC_APP_VERSION`);RTX 5090 文案保留(真实基础设施),但加 hover tooltip 显示 build hash。
  - **为什么**:版本号不能写死。
- **问题 2**:logo 图标 `bg-accent text-white shadow-accent` — logo 容器 8×8 圆角方块 + 主色阴影。
  - **证据**:`sidebar.tsx:55`
  - **改造**:阴影保留(logo 是少有的允许装饰处),但加 `ring-1 ring-accent/20` 微环(避免阴影"飘")。
  - **为什么**:logo 阴影给品牌一点分量,但加 ring 让它"接地"。
- **问题 3**:active nav 状态 `bg-accent-soft` + `bg-accent dot` 双重视觉标记。
  - **证据**:`sidebar.tsx:82, 88`
  - **改造**:删右侧 dot,只保留背景 + 文字 `font-medium`(已加),更克制。
  - **为什么**:双标记是冗余信号,专业工具追求克制度。
- **问题 4**:`dark:bg-[#131318]` 硬编码暗色。
  - **证据**:`sidebar.tsx:52`
  - **改造**:`dark:bg-bg-subtle`(token 化,见 §2.1)。

### 4.2 Dashboard `/dashboard`

- **问题 1**:"总览"页 3 stat cards 全部用 `text-3xl font-semibold`,缺差异化。
  - **证据**:`dashboard/page.tsx:42`
  - **改造**:推荐项(autodl-best)用更大字 + 强调;其他用 meta 字号 + muted。**或者**保留统一但加 `tabular-nums`。
  - **为什么**:统一 3xl 太"卡片网格"味,缺焦点。
- **问题 2**:3 张 stat card 顶部小标都是 `text-sm text-fg-muted` + 右侧 badge,信息冗余(标签已说明,badge 又说一次)。
  - **证据**:`dashboard/page.tsx:38-41`
  - **改造**:只保留左侧小标(去掉 badge hint),badge 移到 hover tooltip 里。
  - **为什么**:信息密度 = 可读性,不该重复。
- **问题 3**:"快速开始"ol 列表用 1/2/3/4 数字 badge — 数字 badge 颜色太抢眼(`bg-accent-soft text-accent`)。
  - **证据**:`dashboard/page.tsx:59`
  - **改造**:数字改为 `text-fg-subtle font-mono`(纯文本),加左侧 1px 竖线区分步骤。
  - **为什么**:专业工具的"步骤指示"应该是克制的标记,不是大彩色徽章。
- **问题 4**:欢迎文案 `"AvatarLoom 灵构——模块化实时数字人运行平台 · AutoDL RTX 5090"` 信息过多。
  - **证据**:`dashboard/page.tsx:30`
  - **改造**:简化 `page-desc` 为"模块化实时数字人运行平台",AutoDL 移到 settings 页(已存在,确认)。
  - **为什么**:总览页只交代产品,具体部署信息在 settings。

### 4.3 Playground `/playground`(核心页,重点改造)

> 这是用户停留最久的页,也是 AI-slop 风险最高的页(有大量 hero / welcome / 渐变 / 装饰)。

#### 4.3.1 `playground-client.tsx` — 状态机结构

- **问题 1**:`conn` 和 `sessionState` 两个独立 state,实际是相关状态机。
  - **证据**:`playground-client.tsx:35-36`
  - **改造**:抽 `useReducer` 或 zustand(不引入新依赖,用 reducer),统一为 `usePlaygroundSession` hook。
  - **为什么**:当前结构在错误路径下会状态不一致(如 `disconnect` 后 `sessionState` 不重置)。
- **问题 2**:`profile_id: "autodl-best"` 硬编码。
  - **证据**:`playground-client.tsx:103`
  - **改造**:从 `localStorage` 读上次选择,或从 `/profiles` API 拿默认推荐项;顶部条加"切换配置"下拉(见 §3.5 ConnectionBar 新组件)。
  - **为什么**:这是产品功能缺口,不是设计问题。但 UI 层要先支持"选 profile"。
- **问题 3**:`ws://${window.location.hostname}:8101/ws/realtime` 硬编码。
  - **证据**:`playground-client.tsx:93`
  - **改造**:从 `process.env.NEXT_PUBLIC_WS_URL` 读,无则 fallback 上面那个(开发用)。
  - **为什么**:部署到生产/不同端口必须可配。

#### 4.3.2 视觉(按严重度)

- **问题 4(最严重)**:`WelcomePane` 用 SVG 画"人脸"作为占位(`head + shoulder + 2 个白点当眼睛`)。
  - **证据**:`playground-client.tsx:514-548`(`<AvatarPortrait>`)
  - **诊断**:**典型 H15 slop**——"用 CSS 剪影/SVG 代替真实产品图"。但项目**真实**有 avatar 上传功能(见 `avatars/page.tsx`)。
  - **改造方案 A(推荐)**:WelcomePane 改为**纯文字 + icon**(无头像区)。`头像 = 真实上传的 avatar`;**未上传时显示"无形象,先到 /avatars 上传"**。
  - **改造方案 B(若坚持)**:把 `<AvatarPortrait>` 删了,改成 lucide `UserCircle2` icon 56px + 中性色 + 简单几何背景(同心圆 / dot grid)。**不要画脸**。
  - **为什么**:这页面是产品门面,假的"小灵"会误导用户以为系统有内置形象。
- **问题 5**:WelcomePane 用了 `radial-gradient` 靛蓝光晕 + `blur-2xl` 圆 + SVG 渐变填充。
  - **证据**:`playground-client.tsx:444-449, 451-454, 521-531`
  - **诊断**:**A2 紫渐变 + F12 渐变背景的轻症**。单色 radial 还算克制,但 + SVG 内 linearGradient + blur 多层叠加 → **视觉糊**。
  - **改造**:删 radial-gradient(用纯 `bg-bg-subtle` 平铺);删 `blur-2xl` 圆;SVG 内改用纯 `fill-accent`(无渐变)。
  - **为什么**:专业工具追求"清晰可读",不是"有氛围感"。
- **问题 6**:`PendingAvatar` 用了 `bg-accent/10 blur-xl animate-pulse`。
  - **证据**:`playground-client.tsx:502`
  - **改造**:删 blur,改用一个**居中的小点 + 文字**(如"等帧 0.3s")。允许一个 `animate-pulse` 圆点做指示器。
  - **为什么**:连接已建立,这是过渡态,不需要"装饰"。
- **问题 7**:聊天气泡 `rounded-2xl shadow-card` — `rounded-2xl`(16px)略大,阴影过重。
  - **证据**:`playground-client.tsx:355, 370`
  - **改造**:改 `rounded-lg`(8px,标准);阴影保留 `shadow-card`(很轻)。
  - **为什么**:与全局圆角 token 对齐,删 slop 圆角。
- **问题 8**:用户气泡用 `bg-accent-soft`(浅靛)+ `text-fg`(深灰)对比度。
  - **证据**:`playground-client.tsx:357`
  - **诊断**:`#eef2ff` 底 + `#0a0a0a` 字 → 对比度约 14:1,通过 WCAG AAA。但视觉上"用户消息"和"系统消息"区分度差(都是浅色)。
  - **改造**:用户气泡用 `bg-accent text-white`(实色主色 + 白字)— 更明显的用户/助手区分。
  - **但要小心**:深底白字长文本可读性下降 → 字数限制 1-2 行。**或者**保留浅底 + 加左侧 3px accent border(类似 G13,但这里有功能意义,不是装饰)。
  - **为什么**:聊天气泡的核心是"谁说的",视觉对比必须强烈。
- **问题 9**:底部控制条 "开始说话" 按钮用了 `shadow-accent`(14px 模糊主色阴影)。
  - **证据**:`playground-client.tsx:390`
  - **诊断**:**典型 C8 slop**——主按钮不该带彩色阴影(只有品牌 logo 允许)。
  - **改造**:删 `shadow-accent`,只保留 `bg-accent text-white border border-accent`。
  - **为什么**:专业工具的按钮 = 边框 + 背景 + 文字,不需要"立体感"。
- **问题 10**:底部"Debug" 复选框 + 调试数字 `frames / audio / queue`。
  - **证据**:`playground-client.tsx:402-416`
  - **诊断**:开发态工具,合理保留。但用了 `text-[10px]`(要改成 11px token)。
  - **改造**:调字号 + 加 `font-mono` 到调试数字(已有)+ 调试数字加 `aria-label="frame count"`。
- **问题 11**:avatar 卡片左下 `小灵 · Demo Assistant` 名字硬编码。
  - **证据**:`playground-client.tsx:296`
  - **改造**:从 `/personas` 拿当前 persona.name + label;无 persona 时显示 "未选 Persona"。
  - **为什么**:当前是"小灵"假名,和真实 persona 系统不一致。
- **问题 12**:连接条 `autodl-best · DeepSeek + VoxCPM2 + MuseTalk` 硬编码。
  - **证据**:`playground-client.tsx:255`
  - **改造**:从 profile 数据动态读 blocks 名;无 profile 时显示"未选运行时配置"。
  - **为什么**:同一个 profile_id 改了就全错。

#### 4.3.3 状态完整性

- **缺 audio level 可视化**:Mic 状态只用 `text-ok` + 闪烁 dot 表达,缺波形条。
  - **改造**(P1):用 `AnalyserNode` 采样 mic 音量,渲染 3-5 根细条形(< 2px 宽,`bg-accent`)— 简易波形指示器。
  - **为什么**:语音交互产品必须有"我在听"的可视化。
- **缺 reconnect 机制**:`onerror` 后只 setState,不会重连。
  - **改造**(P1):加 3 次指数退避重连(500ms / 1s / 2s),失败后给用户"重试"按钮。
  - **为什么**:网络抖动在生产很常见。
- **缺 keyboard shortcut**:空格键切换 mic(交互隐藏但常用)。
  - **改造**(P1):`useEffect` 监听 `keydown`,`Space` 阻止默认 + toggle mic(输入框 focus 时不响应)。

### 4.4 Avatars `/avatars`

- **问题 1**:卡片网格 `grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4` 4 列 — **E11 均匀网格 slop 轻度**。
  - **证据**:`avatars/page.tsx:44`
  - **诊断**:数据可视化场景下 4 列是合理的(头像是视觉资产)。但**断点没在 1280+ 扩到 5 列** → 大屏利用率低。
  - **改造**:加 `xl:grid-cols-5`;缩略图 `aspect-[4/3]` 改 `aspect-[5/4]`(头像更接近方形)。
- **问题 2**:无肖像占位用 `text-fg-subtle text-xs` "无肖像"。
  - **证据**:`avatars/page.tsx:60`
  - **改造**:用 `EmptyState` 组件(图标 `ImageOff` lucide + "无肖像" + "去上传"按钮)— 引导而非空文。
- **问题 3**:`avatars/new/page.tsx` 是单列 form,无 wizard 步骤(选 block 类型 → 上传资产 → 完成)。
  - **诊断**:**P2 锦上添花**。当前单 form 也可接受。
  - **改造**(P2):保留现状,只在 form 上方加 "Avatar Block 选什么?" 的帮助卡片(简述 static / mock / musetalk 区别)。
- **问题 4**:avatar detail 页三列布局(信息 / 预览 / 上传)用了固定 `lg:grid-cols-3` — 中间列闲置(预览/上传的"中"实际是右)。
  - **证据**:`avatars/[id]/page.tsx:50`
  - **改造**:改 `lg:grid-cols-[minmax(260px,1fr)_minmax(420px,2fr)_minmax(280px,1fr)]`,让中间预览列更宽。
  - **为什么**:肖像/视频/音频是视觉资产,应该占更多空间。

### 4.5 Personas `/personas`

- **问题 1**:列表用 `space-y-2.5`(10px) — 非 8pt。
  - **证据**:`personas/page.tsx:34`
  - **改造**:改 `space-y-2`(8px,token 化)。
- **问题 2**:`prompt` 预览 `line-clamp-2` — 适合,但 `p.prompt` 直接渲染没处理空白字符。
  - **证据**:`personas/page.tsx:53`
  - **改造**:加 `whitespace-pre-wrap`(长 prompt 多行)。
- **问题 3**:header 头像圈 `bg-accent-soft text-accent` 48px 大 — slop 中等。
  - **证据**:`personas/page.tsx:39-41`
  - **改造**:头像圈改 32px,`bg-bg-subtle text-fg-muted`(不抢色),旁边加 `text-xs` 的 `v{version}` 标签。
  - **为什么**:列表项的"图标"应该是 hint,不是 hero。

### 4.6 Blocks `/blocks`

- **问题 1**:`h1` 用 `<h1 className="mb-6">` 但其他页用 `page-title` + `page-header` — **不一致**。
  - **证据**:`blocks/page.tsx:21`
  - **改造**:统一为 `page-header` + `page-title` + 可选 `page-desc("已注册的模块定义...")`。
- **问题 2**:分类标题用 `text-sm font-medium text-fg-muted mb-2 uppercase tracking-wide` — 自己实现了一个 section-label。
  - **证据**:`blocks/page.tsx:37`
  - **改造**:替换为 `section-label`(`globals.css:84` 已定义) → `text-[11px] font-semibold uppercase tracking-wider text-fg-subtle`。
  - **为什么**:复用已有 token,避免重复定义。
- **问题 3**:streaming 能力 badge `badge-ok "streaming"` — OK 但没解释 streaming 是什么。
  - **诊断**:**P2**,加 `title="支持流式输出"`。

### 4.7 Profiles `/profiles`

- **问题 1**:`autodl-best` 推荐卡用 `border-accent/40 ring-1 ring-accent/10` — 双重视觉强调。
  - **证据**:`profiles/page.tsx:40`
  - **改造**:只留 `ring-1 ring-accent/30` 即可,删 `border-accent/40`(边框已是 accent,够明显)。
- **问题 2**:"内置 Profile(YAML 文件)" 区放在卡片底部,信息层级混乱 — 既有"运行时配置"实体,又有"文件系统说明"。
  - **证据**:`profiles/page.tsx:71-81`
  - **改造**:把 YAML 列表移到 settings 页(已是服务配置类内容),profiles 页只列运行时配置实体。
  - **为什么**:用户关心的是"我能用哪些 profile",不是"文件在哪"。

### 4.8 Runs `/runs`

- **问题 1**:`h1` 又用了裸 `<h1 className="mb-6">` — 不一致(同 blocks)。
  - **证据**:`runs/page.tsx:15`
  - **改造**:统一为 `page-header` + `page-title`("运行记录")+ `page-desc("每轮对话的录制与指标")`。
- **问题 2**:列表项 metrics 4 列 `grid-cols-2 sm:grid-cols-4` — 在小屏挤压,字号 `text-xs` 太挤。
  - **证据**:`runs/page.tsx:42`
  - **改造**:metric 用 `<dl>` + 自定义 grid,每 metric 占 60px;窄屏只显示 2 个核心 metric("首字" + "总时长"),其他折叠到 detail 页。
- **问题 3**:status badge 只覆盖 3 个状态(`completed / interrupted / error`),其他 fallback 空 — 状态不完整。
  - **证据**:`runs/page.tsx:36`
  - **改造**:扩展 status 映射(`running → badge-accent "进行中"`,`pending → badge "等待中"`)。

### 4.9 Run Detail `/runs/[id]`

- **问题 1**:`<PipelineTimeline>` 用了 `border-2 border-white dark:border-bg-subtle` 给时间线节点。
  - **证据**:`runs/[id]/page.tsx:245-247`
  - **诊断**:用边框"挖洞"模拟环形节点 — 视觉上 OK 但**不标准**。
  - **改造**:用 `ring-2 ring-bg`(亮色模式)或 `shadow-[0_0_0_2px_var(--bg)]`,效果一致但语义更对。
  - **但保持现状也 OK**,这是细节优化,标 P2。
- **问题 2**:`MetricBar` 用了 `bg-accent / bg-warn / bg-ok / bg-fg-subtle` 四种 tone — **G14 数据可视化用色**。
  - **诊断**:四 tone 合理(首字=主色 / 首音=warn / 首帧=ok / 总时长=muted),有功能意义,不算 slop。
  - **保持现状**。
- **问题 3**:`TranscriptBubble` 用了和 Playground 一模一样的样式 — 重复。
  - **证据**:`runs/[id]/page.tsx:264-281` vs `playground-client.tsx:351-367`
  - **改造**:抽 `<MessageBubble role="user"|"assistant">` 到 `components/ui/message-bubble.tsx`,两处复用。
- **问题 4**:artifact 行提示"视频/音频回放需通过产物文件端点访问(暂未开放)" — 把"暂未开放"暴露给用户。
  - **证据**:`runs/[id]/page.tsx:322-325`
  - **改造**:**不要渲染**该占位文字,直接不显示 video/audio 块;等端点开放再加。
  - **为什么**:"暂未开放"是 dev 信息,不该进生产 UI。

### 4.10 Sessions `/sessions`

- **问题 1**:列表只显示 ID + 状态 + 时间,**信息密度过低**(一个会话可能含多次 run)。
  - **证据**:`sessions/page.tsx:24-30`
  - **改造**:每行加 `avatar_id / profile_id / run_count`(从 `/runs?session_id=xxx` 算),让用户能区分不同 session。
- **问题 2**:同 runs — `<h1 className="mb-6">` 不一致。

### 4.11 Settings `/settings`

- **结构 OK**,但**缺"运行时配置预览"** — 用户在 settings 看到服务地址,但看不到当前连接的是哪个 profile / persona。
  - **改造**(P1):加 "当前活动" 卡,显示:
    ```
    运行时配置: autodl-best
    头像:        customer-service-girl
    人设:        客服小灵
    麦克风设备:   MacBook Pro Microphone
    扬声器:      默认
    ```
  - **为什么**:settings 是"系统状态"的天然位置。

### 4.12 移动端响应式

- **现状**:`md` (768px) 是唯一断点。
- **缺失**:
  - Playground 在 `< md` 体验:`grid-cols-1` 堆叠(avatar 上 / 对话下)— 合理但缺"全屏对话"模式。
  - Avatars 4 列在 1280+ 没扩 5 列(见 4.4)。
  - 表单页(avatars/new, personas/new)在移动端没做特殊处理 — 描述 textarea 高度可压缩。
- **改造**(P1):
  - Playground 加"全屏模式"切换(头像藏起来,只显示对话)— 用于纯语音场景。
  - 引入 `sm/md/lg/xl` 完整断点。

---

## 5. 反 AI-slop 检查清单

> 23 项反 slop 全清单,标 ★ 的是当前命中。

### A. 配色(4 项)

| # | 检查 | 当前 | 状态 |
|---|---|---|---|
| A1 | AI 蓝 `#3B82F6` 无品牌理由出现 | 主色是 `#4f46e5` 靛蓝 | ✓ 通过 |
| A2 | 紫色渐变(白底紫→粉/紫→蓝) | 1 处 radial-gradient(WelcomePane) | ★ 轻症 |
| A3 | 凭空发明的新颜色 | 7+ 处硬编码 hex 泄漏 | ★ 命中 |
| A4 | 多色聚类(≥3 分类色堆) | 4 个 metric tone(accent/warn/ok/muted)— 有功能意义 | ✓ 通过 |

### B. 字体(3 项)

| # | 检查 | 当前 | 状态 |
|---|---|---|---|
| B5 | Inter / Roboto / Arial 作 display | 用 system stack `ui-sans-serif, system-ui, ...` | △ 边界(无 display font 差异) |
| B6 | Fraunces / Space Grotesk 跟风 | 无 | ✓ 通过 |
| B7 | display 与 body 无对比 | 单一 fontFamily.sans,仅靠 size/weight | △ 弱(应该有 display + body 配对) |

### C. 阴影(1 项)

| # | 检查 | 当前 | 状态 |
|---|---|---|---|
| C8 | 每卡片都堆 box-shadow | 3 个 shadow token(card/pop/accent),btn-primary 有 `shadow-accent` | ★ 轻症(删 btn 阴影) |

### D. 内容层级(2 项)

| # | 检查 | 当前 | 状态 |
|---|---|---|---|
| D9 | eyebrow+title+desc 三层堆砌 | page-header 只有 title+desc(2 层)— 通过 | ✓ 通过 |
| D10 | 通用 emoji 徽章 | 无 | ✓ 通过 |

### E. 布局节奏(1 项)

| # | 检查 | 当前 | 状态 |
|---|---|---|---|
| E11 | 过于工整的 3/4 列均匀网格 | Avatars 4 列 / Dashboard 3 列 / Metrics 4 列 | △ 轻症(数据场景可接受) |

### F. 渐变(1 项)

| # | 检查 | 当前 | 状态 |
|---|---|---|---|
| F12 | 极端渐变 | 1 处 radial(WelcomePane) + SVG 内 4 处 linear | ★ 轻症(可全删) |

### G. 容器模式(2 项)

| # | 检查 | 当前 | 状态 |
|---|---|---|---|
| G13 | 圆角卡片 + 左彩色 border accent | 无 `border-l-` 使用 | ✓ 通过 |
| G14 | GitHub-dark 偷懒解 | 暗色 token 自定义,不全用 `#0D1117` | ✓ 通过 |

### H. 图像/图标(3 项)

| # | 检查 | 当前 | 状态 |
|---|---|---|---|
| H15 | SVG 画 imagery(人脸/场景) | **AvatarPortrait 画了头+肩+2 个白点当眼睛** | ★★ 重症(必须删) |
| H16 | CSS 剪影/SVG 代替真实产品图 | 同 H15 | ★★ 重症 |
| H17 | 装饰性 icon 每处都配 | sidebar nav 用 icon — 有功能必要(导航) | ✓ 通过 |

### I. 填充内容(3 项)

| # | 检查 | 当前 | 状态 |
|---|---|---|---|
| I18 | Data slop(编造 stats) | "AutoDL RTX 5090"是真实部署 | ✓ 通过 |
| I19 | Quote slop | 无 | ✓ 通过 |
| I20 | Gradient slop(全背景渐变) | 1 处 | ★ 轻症 |

### J. 动画(3 项)

| # | 检查 | 当前 | 状态 |
|---|---|---|---|
| J21 | 散落微交互 vs page load | 抽屉 + toast + drawer 各 200ms 单一动画 | ✓ 通过 |
| J22 | 画面内画底部进度条/时间码 | 无 | ✓ 通过 |
| J23 | PowerPoint 式切换 | 无 | ✓ 通过 |

**汇总**:
- 通过:14 / 23
- 边界:4(可优化)
- 轻症:3(A2, F12, I20, C8)— **都是同源问题:WelcomePane 装饰**
- 重症:1(H15, H16)— **AvatarPortrait SVG 画脸,必须删**

---

## 6. 架构与代码层问题

> 这些是**视觉层之外**但实施规格时必须解决的。

### 6.1 装了不用的依赖

- **问题**:`@tanstack/react-query 5.59` 在 `package.json:16`,`QueryProvider` 在 `query-provider.tsx` 挂载,但**整个 codebase 没有任何 `useQuery` 调用**。
- **建议**:
  - **方案 A(推荐)**:卸载 react-query,删 `QueryProvider` 包装。所有页面是 server component 直接 `apiFetch` — **当前架构其实不需要 client query**。
  - **方案 B**:在 PlaygroundClient 用 react-query 管理 WebSocket 重连 + 状态。
- **为什么该决定**:不用的依赖是噪音,占 70KB+ bundle。

### 6.2 硬编码 WebSocket URL

- **问题**:`playground-client.tsx:93` `ws://${window.location.hostname}:8101/ws/realtime` 硬编码。
- **改造**:
  - 加 `NEXT_PUBLIC_WS_URL` env,默认 fallback 上面那个(开发用)。
  - 加 `<WebSocketProvider>` 或在 settings 页允许用户输入 URL。

### 6.3 硬编码 `profile_id: "autodl-best"`

- **问题**:`playground-client.tsx:103` 写死。
- **改造**:
  - 在 `localStorage` 存 `lastProfileId`,启动时读。
  - 无值时调 `/profiles` API,取第一个 `is_default` 或 fallback `autodl-best`。
  - PlaygroundConnectionBar 加"切换配置"按钮(见 §3.5)。

### 6.4 暗色 token 散落

- **问题**:7+ 处 `dark:bg-[#131318]` / `dark:text-[#ededf2]` 硬编码。
- **改造**:见 §2.1,全部进 `bg-subtle` / `fg` token。

### 6.5 缺统一 EmptyState 组件

- **问题**:6 个页面各自写"暂无 X"提示。
- **改造**:抽 `<EmptyState>`(见 §3.6)。

### 6.6 缺统一 ErrorBanner 组件

- **问题**:6 个页面各自写"Control API 连接失败:..."卡片。
- **改造**:抽 `<ErrorBanner>`(见 §3.7)。

### 6.7 聊天气泡重复

- **问题**:`playground-client.tsx:351-367` 和 `runs/[id]/page.tsx:264-281` 几乎一致。
- **改造**:抽 `<MessageBubble role="user"|"assistant" timestamp?>` 到 `components/ui/message-bubble.tsx`。

### 6.8 缺 `aria-label` 在多个 icon-only 按钮

- **问题**:`asset-uploader.tsx:107` `Loader2` 没 aria,`runs/[id]/page.tsx` 时间线节点没 `role`。
- **改造**:补 aria(本规格视觉层不负责 a11y 语义,但列在 TODO 给 code-reviewer 跟进)。

### 6.9 Loading skeleton 缺 dark mode 适配校验

- **现状**:`skeleton.tsx:11` `dark:bg-border/30` — OK。
- **保持现状**。

### 6.10 PlaygroundClient 文件过大

- **问题**:`playground-client.tsx` 549 行 — 含 3 个内部子组件(`WelcomePane` / `PendingAvatar` / `AvatarPortrait`)。
- **改造**(P2):抽到 `components/playground/` 目录:
  - `connection-bar.tsx`
  - `welcome-pane.tsx`
  - `pending-avatar.tsx`
  - `transcript-pane.tsx`
  - `control-bar.tsx`
  - `playground-client.tsx` 只做 orchestration。

---

## 7. 优先级排序与投入产出

### P0 — 必修(每条 < 2h,影响 > 80% 观感)

| # | 任务 | 投入 | 收益 | 引证 |
|---|---|---|---|---|
| P0-1 | 删 `AvatarPortrait` SVG 画脸(WelcomePane) | 0.5h | **去掉最严重 slop,符合"真实优先"** | `playground-client.tsx:514-548` |
| P0-2 | 删 `WelcomePane` radial-gradient + blur-2xl | 0.5h | 去 A2/F12/C8 三个 slop | `playground-client.tsx:444-454` |
| P0-3 | 删 `btn-primary` 的 `shadow-accent` | 0.1h | 去 C8 | `playground-client.tsx:390`, `globals.css:39` |
| P0-4 | 替换 7 处暗色硬编码 hex → token | 1h | 主题系统干净,改色一处生效 | `sidebar.tsx:52`, `runs/[id]/page.tsx:207,250,295`, `playground-client.tsx:277,457,477` |
| P0-5 | 抽 `<EmptyState>` 组件,替换 6 处 | 1h | 跨页一致,空态不再千篇一律 | runs/avatars/personas/blocks/sessions/profiles |
| P0-6 | 抽 `<ErrorBanner>` 组件,替换 6 处 | 0.5h | 错误信息一致 | 同上 |
| P0-7 | 统一 `page-header` 使用(runs/blocks/sessions) | 0.3h | 跨页标题结构一致 | runs/page.tsx:15, blocks/page.tsx:21, sessions/page.tsx:14 |
| P0-8 | 把 `wsUrl` 和 `profile_id` 从源码移到 env + localStorage | 1h | 部署/切换可配 | `playground-client.tsx:93,103` |

**P0 合计:约 5h,1 个工作日。**

### P1 — 建议(影响中等,投入 0.5-2 天)

| # | 任务 | 投入 | 收益 |
|---|---|---|---|
| P1-1 | Playground `useReducer` 状态机重构 | 4h | 修状态不一致 bug,代码可读 |
| P1-2 | 抽 `<MessageBubble>` 共享组件 | 1h | 减少重复 |
| P1-3 | Playground 加 audio level 可视化(简易波形) | 3h | 核心 UX 提升 |
| P1-4 | Playground 加 reconnect 机制(3 次指数退避) | 2h | 网络抖动恢复 |
| P1-5 | Playground 加 keyboard shortcut(空格切麦) | 1h | 提升操作效率 |
| P1-6 | Settings 加"当前活动"卡 | 2h | 状态可见性 |
| P1-7 | Avatars detail 三列改弹性 grid | 0.5h | 视觉资产占更多空间 |
| P1-8 | 引入 `sm/md/lg/xl` 完整断点 | 2h | 大屏利用率 |
| P1-9 | 决定 react-query 命运(卸/用) | 1h | 减 70KB+ bundle 或用上 |
| P1-10 | 抽 playground 子组件(6 个文件) | 3h | 单一职责,可测 |

**P1 合计:约 2 个工作日。**

### P2 — 锦上添花(不紧急,攒起来)

- 跑分对比 + 柱图(small multiples 替代 single bar)
- Avatars 缩略图改 5:4
- Blocks 分组卡片 hover 展示 streaming 解释 tooltip
- 国际化(i18n)— 当前全中文,接外单需双语
- 暗色 token 全 CSS 变量化(下一步演进方向)
- 真实用户头像/人设时,Playground 直接渲染 `<img>` 替代 SVG
- 把 `playground-client.tsx:447` 那种 inline radial 完全删掉,改用 token class
- 设置页支持用户上传 OCI 镜像 / API Key 管理(产品功能)

---

## 8. 实施注意事项

### 8.1 风格选择 vs 问题的边界(写给下一位开发者)

- **不动的**:`autodl-best · DeepSeek + VoxCPM2 + MuseTalk` 副标文字 — 这是产品真实依赖,不是 slop。
- **可改但不强求**:4 列 Avatars 网格 — 数据场景下均匀合理,只是大屏可加第 5 列。
- **必改的**:WelcomePane 那个 96×96 SVG 圆脸 — 这不是"风格选择",是 AI 标志。

### 8.2 实施顺序

1. **P0 一次推完**(约 1 个工作日)— 这批只改 token + 删 slop,不动业务逻辑,风险极低。
2. **P1 分批**(每批一个 PR)— 先做 P1-1(状态机)+ P1-3(波形)+ P1-6(当前活动卡)这三个高 ROI 的。
3. **P2 攒 1 个月后回顾** — 产品定位可能变,不必提前做。

### 8.3 不要做的事

- **不要** 引入新的 UI 库(shadcn/Antd/MUI)— 现有 4 个 utility class 已够用,引入会破坏克制感。
- **不要** 把所有色都换 oklch — 当前 hex 调色板已经过实测对比度,改 oklch 收益小,改错风险大。
- **不要** 在没有设计师参与下,自行"优化"任何一张图(如 portrait、logo)— 这些是 brand asset。
- **不要** 给 page-title 加 emoji(🍃 灵构 Studio 之类)— 项目硬约束。

### 8.4 验证清单(每个 PR 完成后跑一次)

- [ ] 桌面端 1440×900 截图,dashboard / playground / runs / avatars
- [ ] 移动端 375×667 截图,playground drawer 展开
- [ ] 暗色模式截图(全部页面)
- [ ] Lighthouse a11y ≥ 90
- [ ] Bundle size 变化 ≤ ±5KB(没装新依赖前提下)

### 8.5 与其他文档的关系

- `docs/01-架构与模块规范.md` — 关注后端架构,本规格不涉及
- `docs/02-事件协议状态机与音画同步.md` — 提到 PlaygroundClient 状态机,本规格 P1-1 的状态机重构应该参考它的协议定义
- `docs/03-Studio部署安全与验收.md` — 部署相关,本规格的 `NEXT_PUBLIC_WS_URL` env 配置要写到那里
- `docs/06-MuseTalk-real-lipsync-ui-report.md` — MuseTalk 集成的 UI 报告,本规格不重复
- `docs/07-handover-next-dev.md` — 交接文档,本规格可作为它的"UI 部分"附录

---

## 附录 A — 当前文件清单(已审,2026-08-06)

| 文件 | 行数 | 评级 | 主要问题 |
|---|---|---|---|
| `app/layout.tsx` | 40 | ✓ 通过 | — |
| `app/page.tsx` | 5 | ✓ 通过 | 仅 redirect |
| `app/globals.css` | 86 | △ 弱 | 4 个 utility class OK,但 btn-primary 阴影过重 |
| `tailwind.config.ts` | 41 | △ 弱 | 缺 info / soft variant / duration token |
| `components/layout/app-shell.tsx` | 95 | △ 弱 | backdrop-blur 性能、触控目标 36px 偏小 |
| `components/layout/sidebar.tsx` | 106 | △ 弱 | 暗色硬编码、active 双重标记冗余 |
| `components/layout/theme-toggle.tsx` | 56 | ✓ 通过 | 实现干净 |
| `components/layout/query-provider.tsx` | 16 | △ 弱 | 整个项目不用 react-query |
| `components/audio/playground-client.tsx` | 549 | ★★ 重点改造 | 见 §4.3 |
| `components/avatar/asset-uploader.tsx` | 120 | ✓ 通过 | 干净 |
| `components/avatar/create-form.tsx` | 105 | ✓ 通过 | 干净 |
| `components/avatar/voice-text-editor.tsx` | 48 | ✓ 通过 | 极简,OK |
| `components/persona/create-form.tsx` | 108 | ✓ 通过 | 干净 |
| `components/ui/toast.tsx` | 148 | ✓ 通过 | 干净,4 秒 TTL 合理 |
| `components/ui/skeleton.tsx` | 16 | ✓ 通过 | 干净 |
| `lib/api.ts` | 204 | ✓ 通过 | 类型定义清晰 |
| `lib/audio/recorder.ts` | 121 | ✓ 通过 | 简洁 |
| `lib/audio/player.ts` | 117 | ✓ 通过 | 简洁 |
| `lib/audio/sync.ts` | 102 | ✓ 通过 | 策略清晰 |
| `app/dashboard/page.tsx` | 74 | △ 弱 | 步骤 badge 太抢,stat 卡片重复标签 |
| `app/playground/page.tsx` | 15 | ✓ 通过 | 仅壳 |
| `app/runs/page.tsx` | 70 | △ 弱 | page-header 缺、metrics 4 列挤压 |
| `app/runs/[id]/page.tsx` | 355 | △ 弱 | 暗色硬编码、bubble 重复、artifact 暴露 dev 信息 |
| `app/avatars/page.tsx` | 80 | △ 弱 | 4 列网格 OK,空态用 EmptyState |
| `app/avatars/new/page.tsx` | 18 | ✓ 通过 | 极简 |
| `app/avatars/[id]/page.tsx` | 193 | △ 弱 | 三列固定宽,中间列闲置 |
| `app/personas/page.tsx` | 61 | △ 弱 | 头像圈太抢,space-y 非 8pt |
| `app/personas/new/page.tsx` | 26 | ✓ 通过 | 极简 |
| `app/blocks/page.tsx` | 63 | △ 弱 | page-header 缺,自实现 section-label |
| `app/profiles/page.tsx` | 84 | △ 弱 | 推荐卡双重强调,YAML 列表该移到 settings |
| `app/sessions/page.tsx` | 37 | △ 弱 | 信息密度低,page-header 缺 |
| `app/settings/page.tsx` | 45 | △ 弱 | 缺"当前活动"卡 |

---

**版本**:v1.0 · 2026-08-06 · 基于静态读码
**下次更新触发**:P0 改完后回填实测;P1-1 状态机完成后补"状态图"
