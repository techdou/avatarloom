"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { clsx } from "clsx";
import { Mic, Square, AlertCircle, UserCircle2, History } from "lucide-react";
import {
  useRealtimeSession,
  STATE_META_FALLBACK,
} from "@/hooks/use-realtime-session";
import { ContextBar } from "@/components/playground/context-bar";
import { DebugDrawer } from "@/components/playground/debug-drawer";

/**
 * Realtime Playground —— 简洁对话式 Avatar 界面（对话优先信息架构）。
 *
 * 数据流（WS / PCM / AVMux / MicrophoneRecorder）全部在 useRealtimeSession hook 内；
 * 本组件是纯渲染层 + ContextBar 交互。音频是主时钟：PcmPlayer 用 AudioContext.currentTime
 * 调度，AVMux 按节奏消费帧。
 *
 * profile/persona 不再硬编码：由 ContextBar 选择并存 localStorage，session.start 时由 hook 上送。
 */
const STATE_META = STATE_META_FALLBACK;

export function PlaygroundClient() {
  // profile / persona：客户端持久化（默认 autodl-best / demo-assistant）
  const [profileId, setProfileId] = useState<string>("autodl-best");
  const [personaId, setPersonaId] = useState<string>("demo-assistant");
  const [showDebug, setShowDebug] = useState(false);
  const [runsOpen, setRunsOpen] = useState(false);

  useEffect(() => {
    try {
      const p = localStorage.getItem("al.profile");
      const pe = localStorage.getItem("al.persona");
      if (p) setProfileId(p);
      if (pe) setPersonaId(pe);
    } catch {
      /* ignore */
    }
  }, []);

  const session = useRealtimeSession({ profileId, personaId });

  const restartSession = useCallback(() => {
    // 已连接时切换 profile/persona：重启会话让新配置生效
    session.disconnect();
    setTimeout(() => session.connect(), 100);
  }, [session]);

  const handleProfileChange = useCallback(
    (id: string) => {
      setProfileId(id);
      try {
        localStorage.setItem("al.profile", id);
      } catch {
        /* ignore */
      }
      if (session.conn === "connected") restartSession();
    },
    [restartSession, session.conn]
  );

  const handlePersonaChange = useCallback(
    (id: string) => {
      setPersonaId(id);
      try {
        localStorage.setItem("al.persona", id);
      } catch {
        /* ignore */
      }
      if (session.conn === "connected") restartSession();
    },
    [restartSession, session.conn]
  );

  const chatRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = chatRef.current;
    // jsdom / 某些环境没有 scrollTo——guard 一下避免渲染期抛错
    if (el && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [session.transcript, session.llmDelta]);

  const stateMeta = STATE_META[session.sessionState] || STATE_META.idle;

  return (
    <div className="flex flex-col gap-2 h-[calc(100vh-3.5rem)] md:h-[calc(100vh-0px)] md:p-2">
      {/* 顶部上下文条（连接 / profile / persona / 调试 / 主题） */}
      <ContextBar
        conn={session.conn}
        profileId={profileId}
        personaId={personaId}
        onProfileChange={handleProfileChange}
        onPersonaChange={handlePersonaChange}
        onConnect={session.connect}
        onDisconnect={session.disconnect}
        showDebug={showDebug}
        onToggleDebug={setShowDebug}
      />

      {/* 主区：角色（左/上） + 对话（右/下） */}
      <div className="grid grid-cols-1 grid-rows-[50vh_1fr] md:grid-rows-none md:grid-cols-[minmax(360px,420px)_1fr] gap-2 flex-1 min-h-0">
        {/* Avatar 区 */}
        <div className="card flex flex-col overflow-hidden p-0 min-h-0">
          <div className="relative flex-1 min-h-0 bg-bg-subtle flex items-center justify-center overflow-hidden dark:bg-[#131318]">
            {session.frameUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={session.frameUrl} alt="avatar" className="w-full h-full object-cover" />
            ) : session.conn === "disconnected" || session.conn === "error" ? (
              <WelcomePane conn={session.conn} error={session.error} onConnect={session.connect} />
            ) : (
              <PendingAvatar />
            )}
            {showDebug && (
              <div className="absolute top-2 left-2 text-[10px] font-mono bg-black/60 text-white px-2 py-1 rounded-md">
                {session.sessionState} · 帧 {session.debugInfo.framesShown}
              </div>
            )}
          </div>
        </div>

        {/* 对话面板 */}
        <div className="card flex flex-col p-0 min-h-0">
          {/* 对话区 header：桌面端显示，移动端隐藏（空间留给对话） */}
          <div className="hidden md:flex px-4 py-3 border-b border-border items-center justify-between dark:border-border">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">对话</span>
              <span className={clsx("badge", stateMeta.badge)}>{stateMeta.label}</span>
            </div>
            <div className="flex items-center gap-3">
              {session.sessionId && (
                <div className="text-[10px] font-mono text-fg-subtle truncate max-w-[200px]">
                  {session.sessionId}
                </div>
              )}
              <button
                type="button"
                onClick={() => setRunsOpen(true)}
                className="btn btn-sm btn-ghost inline-flex items-center gap-1"
                title="运行记录"
              >
                <History className="w-3.5 h-3.5" />
                历史
              </button>
            </div>
          </div>

          <div ref={chatRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
            {session.error && (
              <div className="rounded-lg border border-err/30 bg-err/5 text-err text-xs px-3 py-2">
                {session.error}
              </div>
            )}
            {session.transcript.length === 0 && !session.llmDelta && (
              <div className="h-full flex flex-col items-center justify-center text-center text-fg-subtle px-6">
                <div className={clsx(
                  "w-14 h-14 rounded-2xl flex items-center justify-center mb-3 transition-colors",
                  session.conn === "connected"
                    ? "bg-accent-soft text-accent dark:bg-accent/15"
                    : "bg-border/40 text-fg-subtle"
                )}>
                  <Mic className="w-6 h-6" />
                </div>
                <div className="text-sm font-medium text-fg-muted dark:text-fg-muted mb-1">
                  {session.conn === "connected" ? "准备就绪" : "等待连接"}
                </div>
                {/* 移动端精简文案；桌面端保留说明 */}
                <div className="hidden md:block text-xs">
                  {session.conn === "connected"
                    ? "点击下方麦克风按钮，开始语音对话。讲话时数字人会实时听写并回复。"
                    : "先连接 Runtime Gateway，再开启麦克风。"}
                </div>
                <div className="md:hidden text-xs">
                  {session.conn === "connected" ? "点击麦克风开始对话" : "先连接再开启麦克风"}
                </div>
              </div>
            )}
            {session.transcript.map((item, i) => (
              <div key={i} className={clsx("flex", item.role === "user" ? "justify-end" : "justify-start")}>
                <div
                  className={clsx(
                    "max-w-[78%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed shadow-card",
                    item.role === "user"
                      ? "bg-accent-soft text-fg rounded-br-md dark:bg-accent/15"
                      : "bg-white border border-border rounded-bl-md dark:bg-bg-subtle dark:border-border"
                  )}
                >
                  <div className="text-[10px] text-fg-subtle mb-1">
                    {item.role === "user" ? "你" : "小灵"}
                  </div>
                  <div className="whitespace-pre-wrap break-words">{item.text}</div>
                </div>
              </div>
            ))}
            {session.llmDelta && (
              <div className="flex justify-start">
                <div className="max-w-[78%] rounded-2xl rounded-bl-md bg-white border border-border px-3.5 py-2.5 text-sm leading-relaxed shadow-card dark:bg-bg-subtle dark:border-border">
                  <div className="text-[10px] text-fg-subtle mb-1">小灵 · 思考中</div>
                  <div className="whitespace-pre-wrap break-words">
                    {session.llmDelta}
                    <span className="inline-block w-1.5 h-3.5 bg-accent ml-0.5 align-middle animate-pulse" />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* 底部控制条 */}
          <div className="px-4 py-3 border-t border-border flex items-center gap-2 dark:border-border">
            {/* 移动端放大圆形麦克风；桌面端回归文字按钮 */}
            <button
              onClick={session.toggleMic}
              disabled={session.conn !== "connected"}
              aria-label={session.micActive ? "停止麦克风" : "开始说话"}
              className={clsx(
                "inline-flex items-center justify-center gap-2 rounded-full md:rounded-xl transition-all active:scale-[0.98]",
                "w-14 h-14 md:w-auto md:h-auto px-4 md:py-2.5 text-sm font-medium",
                session.micActive
                  ? "bg-err/10 text-err border border-err/30"
                  : "bg-accent text-white border border-accent disabled:opacity-40"
              )}
            >
              {session.micActive ? (
                <Square className="w-6 h-6 md:w-4 md:h-4" />
              ) : (
                <Mic className="w-6 h-6 md:w-4 md:h-4" />
              )}
              <span className="hidden md:inline">
                {session.micActive ? "停止麦克风" : "开始说话"}
              </span>
            </button>
            {session.playing && (
              <button onClick={session.interrupt} className="btn btn-danger">
                打断
              </button>
            )}
            {showDebug && (
              <div className="ml-auto text-[10px] font-mono text-fg-subtle">
                {session.debugInfo.framesShown}f · {session.debugInfo.audioChunks}a · q{session.debugInfo.queueLen}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 运行记录侧滑（第四步注入；动态导入避免首屏负担） */}
      {runsOpen && <RunsOverlayDeferred onClose={() => setRunsOpen(false)} />}

      {/* 调试抽屉（开关在 ContextBar） */}
      {showDebug && (
        <DebugDrawer
          conn={session.conn}
          sessionState={session.sessionState}
          sessionId={session.sessionId}
          debugInfo={session.debugInfo}
          timing={session.timing}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 视觉占位子组件（纯展示，不参与数据流）
// ---------------------------------------------------------------------------

/** 未连接引导态：克制占位 + 连接 CTA。已删 SVG 假脸 / radial-gradient / blur 装饰。 */
function WelcomePane({
  conn,
  error,
  onConnect,
}: {
  conn: ReturnType<typeof useRealtimeSession>["conn"];
  error: string | null;
  onConnect: () => void;
}) {
  const connecting = conn === "connecting";
  return (
    <div className="w-full h-full flex flex-col items-center justify-center px-6 py-8 text-center">
      <UserCircle2 className="w-16 h-16 text-accent/60 dark:text-accent/50" strokeWidth={1.25} />

      <div className="max-w-xs mt-4">
        <div className="text-base font-semibold tracking-tight text-fg dark:text-[#ededf2]">
          实时数字人 · 小灵
        </div>
        <p className="text-xs text-fg-muted mt-1.5 leading-relaxed dark:text-fg-muted">
          连接 Runtime Gateway 即可开启低延迟语音对话。
          音频为主时钟，口型与表情自动同步。
        </p>

        {/* 能力 chips */}
        <div className="flex flex-wrap items-center justify-center gap-1.5 mt-3">
          <span className="badge badge-accent text-[10px]">DeepSeek LLM</span>
          <span className="badge text-[10px]">VoxCPM2 TTS</span>
          <span className="badge text-[10px]">MuseTalk</span>
        </div>

        <button
          type="button"
          onClick={onConnect}
          disabled={connecting}
          className="btn btn-primary w-full mt-4"
        >
          {connecting ? "连接中…" : "连接并开始"}
        </button>

        {error ? (
          <div className="mt-2.5 flex items-start gap-1.5 text-[11px] text-err text-left">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span className="leading-snug">{error}</span>
          </div>
        ) : (
          <div className="mt-2.5 text-[11px] text-fg-subtle">
            需要本地 Runtime Gateway 监听 <code className="font-mono">:8101</code>
          </div>
        )}
      </div>
    </div>
  );
}

/** 已连接、等待第一帧的占位。 */
function PendingAvatar() {
  return (
    <div className="w-full h-full flex flex-col items-center justify-center">
      <UserCircle2
        className="w-16 h-16 text-accent/60 dark:text-accent/50 animate-pulse"
        strokeWidth={1.25}
      />
      <div className="mt-4 text-xs text-fg-muted dark:text-fg-muted flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
        等待角色画面…
      </div>
    </div>
  );
}

/** 运行记录侧滑——延迟加载 RunsPanel，避免打断首屏。 */
function RunsOverlayDeferred({ onClose }: { onClose: () => void }) {
  const [Node, setNode] = useState<React.ReactNode>(null);
  useEffect(() => {
    let alive = true;
    import("@/components/playground/runs-panel")
      .then((m) => {
        if (alive) setNode(<m.RunsPanel onClose={onClose} />);
      })
      .catch(() => {
        if (alive) setNode(null);
      });
    return () => {
      alive = false;
    };
  }, [onClose]);
  return Node;
}
