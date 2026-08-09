"use client";

import { memo, useEffect, useRef } from "react";
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
  /** 麦克风音量采样（0-1）。传则激活时显示波形条。 */
  getMicLevel?: () => number;
}

/**
 * Playground 底部控制条——麦克风主按钮 + 音量波形 + 打断 + 调试数字（调试模式时）。
 * 移动端：圆形大麦克风（触控优先）；桌面端：文字按钮（空格键切换）。
 *
 * React.memo：调试模式开启时仍需 debugInfo 实时刷新数字，但调试关闭时
 * debugInfo 的 25/s 更新不会触发重渲染（浅比较看 props 是否变化，未变即跳过）。
 */
export const ControlBar = memo(function ControlBar({
  conn,
  micActive,
  playing,
  onToggleMic,
  onInterrupt,
  showDebug,
  debugInfo,
  getMicLevel,
}: ControlBarProps) {
  return (
    <div className="px-4 py-3 border-t border-border flex items-center gap-2 dark:border-border">
      <button
        onClick={onToggleMic}
        disabled={conn !== "connected"}
        aria-label={micActive ? "停止麦克风" : "开始说话"}
        title="空格键切换麦克风"
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
      {micActive && getMicLevel && <MicLevelBars getLevel={getMicLevel} />}
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
});

/** 麦克风音量指示——5 根细条按 RMS 阈值点亮。rAF 直改 DOM，不触发 React 重渲染。 */
function MicLevelBars({ getLevel }: { getLevel: () => number }) {
  const barsRef = useRef<(HTMLSpanElement | null)[]>([]);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const level = getLevel();
      for (let i = 0; i < 5; i++) {
        const bar = barsRef.current[i];
        if (!bar) continue;
        // 阈值递进 + 留一点迟滞，视觉更稳
        bar.style.opacity = level >= (i + 1) * 0.16 ? "1" : "0.25";
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [getLevel]);

  return (
    <span className="flex items-center gap-[3px] h-4" aria-label="麦克风音量">
      {[0, 1, 2, 3, 4].map((i) => (
        <span
          key={i}
          ref={(el) => {
            barsRef.current[i] = el;
          }}
          className="w-[3px] rounded-full bg-accent transition-opacity duration-quick"
          style={{ height: `${6 + i * 2}px`, opacity: 0.25 }}
        />
      ))}
    </span>
  );
}
