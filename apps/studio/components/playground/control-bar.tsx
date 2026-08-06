"use client";

import { clsx } from "clsx";
import { Mic, Square } from "lucide-react";
import type { ConnState, DebugInfo } from "@/hooks/use-realtime-session";

interface ControlBarProps {
  conn: ConnState;
  micActive: boolean;
  playing: boolean;
  onToggleMic: () => void;
  onInterrupt: () => void;
  showDebug: boolean;
  debugInfo: DebugInfo;
}

/**
 * Playground 底部控制条——麦克风主按钮 + 打断 + 调试数字（调试模式时）。
 * 移动端：圆形大麦克风（触控优先）；桌面端：文字按钮。
 */
export function ControlBar({
  conn,
  micActive,
  playing,
  onToggleMic,
  onInterrupt,
  showDebug,
  debugInfo,
}: ControlBarProps) {
  return (
    <div className="px-4 py-3 border-t border-border flex items-center gap-2 dark:border-border">
      <button
        onClick={onToggleMic}
        disabled={conn !== "connected"}
        aria-label={micActive ? "停止麦克风" : "开始说话"}
        className={clsx(
          "inline-flex items-center justify-center gap-2 rounded-full md:rounded-xl transition-all active:scale-[0.98]",
          "w-14 h-14 md:w-auto md:h-auto px-4 md:py-2.5 text-sm font-medium",
          micActive
            ? "bg-err/10 text-err border border-err/30"
            : "bg-accent text-white border border-accent disabled:opacity-40"
        )}
      >
        {micActive ? (
          <Square className="w-6 h-6 md:w-4 md:h-4" />
        ) : (
          <Mic className="w-6 h-6 md:w-4 md:h-4" />
        )}
        <span className="hidden md:inline">
          {micActive ? "停止麦克风" : "开始说话"}
        </span>
      </button>
      {playing && (
        <button onClick={onInterrupt} className="btn btn-danger">
          打断
        </button>
      )}
      {showDebug && (
        <div className="ml-auto text-micro font-mono text-fg-subtle">
          {debugInfo.framesShown}f · {debugInfo.audioChunks}a · q{debugInfo.queueLen}
        </div>
      )}
    </div>
  );
}
