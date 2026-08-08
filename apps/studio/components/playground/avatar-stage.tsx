"use client";

import { UserCircle2 } from "lucide-react";
import type { ConnState } from "@/hooks/use-realtime-session";

interface AvatarStageProps {
  frameUrl: string | null;
  conn: ConnState;
  error: string | null;
  onConnect: () => void;
  showDebug: boolean;
  sessionState: string;
  framesShown: number;
  personaLabel: string;
  /** 实际 WS 目标地址（未连接提示用，替代写死的端口文案）。 */
  wsUrl: string | null;
}

/**
 * 数字人画面区——帧显示 / 未连接引导 / 等帧占位 三态。
 * 纯展示组件，不参与数据流；画面 blob URL 由 useRealtimeSession 维护。
 */
export function AvatarStage({
  frameUrl,
  conn,
  error,
  onConnect,
  showDebug,
  sessionState,
  framesShown,
  personaLabel,
  wsUrl,
}: AvatarStageProps) {
  return (
    <div className="card flex flex-col overflow-hidden p-0 min-h-0">
      <div className="relative flex-1 min-h-0 bg-bg-subtle flex items-center justify-center overflow-hidden dark:bg-bg-subtle-dark">
        {frameUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={frameUrl} alt="avatar" className="w-full h-full object-cover" />
        ) : conn === "disconnected" || conn === "error" ? (
          <WelcomePane conn={conn} error={error} onConnect={onConnect} personaLabel={personaLabel} wsUrl={wsUrl} />
        ) : (
          <PendingAvatar />
        )}
        {showDebug && (
          <div className="absolute top-2 left-2 text-micro font-mono bg-black/60 text-white px-2 py-1 rounded-md">
            {sessionState} · 帧 {framesShown}
          </div>
        )}
      </div>
    </div>
  );
}

/** 未连接引导态：克制占位 + 连接 CTA + 真实 WS 目标地址。 */
function WelcomePane({
  conn,
  error,
  onConnect,
  personaLabel,
  wsUrl,
}: {
  conn: ConnState;
  error: string | null;
  onConnect: () => void;
  personaLabel: string;
  wsUrl: string | null;
}) {
  const connecting = conn === "connecting";
  return (
    <div className="w-full h-full flex flex-col items-center justify-center px-6 py-8 text-center">
      <UserCircle2 className="w-16 h-16 text-accent/60 dark:text-accent/50" strokeWidth={1.25} />

      <div className="max-w-xs mt-4">
        <div className="text-base font-semibold tracking-tight text-fg dark:text-fg-dark">
          实时数字人 · {personaLabel}
        </div>
        <p className="text-xs text-fg-muted mt-1.5 leading-relaxed">
          连接 Runtime Gateway 即可开启低延迟语音对话。
          音频为主时钟，口型与表情自动同步。
        </p>

        <button
          type="button"
          onClick={onConnect}
          disabled={connecting}
          className="btn btn-primary w-full mt-4"
        >
          {connecting ? "连接中…" : "连接并开始"}
        </button>

        {error ? (
          <div className="mt-2.5 text-micro text-err text-left leading-snug">{error}</div>
        ) : (
          <div className="mt-2.5 text-micro text-fg-subtle">
            将连接 <code className="font-mono">{wsUrl ?? "ws://…"}</code>
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
      <div className="mt-4 text-xs text-fg-muted flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
        等待角色画面…
      </div>
    </div>
  );
}
