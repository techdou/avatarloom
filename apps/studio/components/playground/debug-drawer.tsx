"use client";

import { memo, useEffect, useState } from "react";
import { clsx } from "clsx";
import { ChevronUp, ChevronDown } from "lucide-react";
import type { DebugInfo, SessionTiming, ConnState } from "@/hooks/use-realtime-session";
import { STATE_META_FALLBACK } from "@/hooks/use-realtime-session";
import { currentRoundEvents, roundLatencies, type SessionEvent } from "@/lib/events";

interface DebugDrawerProps {
  conn: ConnState;
  sessionState: string;
  sessionId: string | null;
  debugInfo: DebugInfo;
  timing: SessionTiming;
  events: SessionEvent[];
}

/** 会话状态机的主要阶段（进度点用）。idle/interrupting/error 不占位。 */
const STAGES = [
  { key: "listening", label: "聆听" },
  { key: "transcribing", label: "识别" },
  { key: "thinking", label: "思考" },
  { key: "speaking", label: "回复" },
] as const;

/**
 * 底部调试抽屉 v2——Playground 作为"可对话调试器"的核心面板。
 *
 * 收起态：状态徽章 + 水位数字一行。
 * 展开态：阶段进度点 + 左栏本轮实时事件流（terminal 风）+ 右栏里程碑延迟 / 水位 / session。
 * 数据全部来自 useRealtimeSession 的 events/timing（前端本地收集，无后端依赖）。
 *
 * React.memo：调试抽屉默认就吃 debugInfo/events 的高频更新（这是它的职责），
 * 但 PlaygroundClient 在非调试态时不会挂载本组件；memo 主要避免父级其它无关状态
 * 变化（如 profile/persona 下拉列表加载完成）误触重渲染。
 */
export const DebugDrawer = memo(function DebugDrawer({
  conn,
  sessionState,
  sessionId,
  debugInfo,
  timing,
  events,
}: DebugDrawerProps) {
  const [open, setOpen] = useState(false);

  // 展开态下按 ESC 收起
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const round = currentRoundEvents(events);
  const base = round[0]?.ts ?? null;
  const lat = roundLatencies(timing);
  const currentStage = STAGES.findIndex((s) => s.key === sessionState);
  const stateMeta = STATE_META_FALLBACK[sessionState] ?? STATE_META_FALLBACK.idle;

  return (
    <div className="border-t border-border bg-white dark:bg-bg-subtle-dark dark:border-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 h-9 text-xs font-medium text-fg-muted hover:bg-bg-subtle dark:hover:bg-border/30 transition-colors"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2">
          {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
          调试
          <span className={clsx("badge text-micro", stateMeta.badge)}>{stateMeta.label}</span>
        </span>
        <span className="font-mono text-micro text-fg-subtle">
          {debugInfo.framesShown}f · {debugInfo.audioChunks}a · q{debugInfo.queueLen}
        </span>
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-3">
          {/* 阶段进度点 */}
          <div className="flex items-center gap-4 pt-1">
            {STAGES.map((s, i) => {
              const done = currentStage > i;
              const active = currentStage === i;
              return (
                <span key={s.key} className="flex items-center gap-1.5 text-micro">
                  <span
                    className={clsx(
                      "w-2 h-2 rounded-full",
                      active
                        ? "bg-accent animate-pulse"
                        : done
                          ? "bg-accent"
                          : "bg-border dark:bg-border"
                    )}
                  />
                  <span className={active || done ? "text-fg dark:text-fg-dark" : "text-fg-subtle"}>
                    {s.label}
                  </span>
                </span>
              );
            })}
            {sessionState === "interrupting" && (
              <span className="text-micro text-err">打断中</span>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            {/* 左栏：本轮实时事件流 */}
            <div className="rounded-md border border-border p-2.5 dark:border-border min-w-0">
              <div className="section-label mb-2">本轮事件流</div>
              {round.length === 0 ? (
                <div className="text-micro text-fg-subtle py-3 text-center">
                  暂无事件——开口说一轮后此处出现事件流
                </div>
              ) : (
                <ol className="space-y-1 font-mono text-micro max-h-56 overflow-y-auto">
                  {round.map((ev, i) => (
                    <li key={i} className="flex items-baseline gap-2">
                      <span className="w-14 shrink-0 text-right text-fg-subtle tabular-nums">
                        {base != null ? `+${ev.ts - base}ms` : "—"}
                      </span>
                      <span
                        className={clsx(
                          "shrink-0",
                          ev.type === "error" ? "text-err" : "text-fg dark:text-fg-dark"
                        )}
                      >
                        {ev.type}
                      </span>
                      {ev.summary && (
                        <span className="text-fg-subtle truncate">{ev.summary}</span>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </div>

            {/* 右栏：里程碑延迟 + 水位 + session */}
            <div className="rounded-md border border-border p-2.5 space-y-1.5 dark:border-border">
              <div className="section-label mb-1">里程碑（相对 t0）</div>
              <Kv k="首字 LLM" v={lat.firstTextMs != null ? `${lat.firstTextMs}ms` : "—"} />
              <Kv k="首音 TTS" v={lat.firstAudioMs != null ? `${lat.firstAudioMs}ms` : "—"} />
              <Kv k="首帧 Avatar" v={lat.firstFrameMs != null ? `${lat.firstFrameMs}ms` : "—"} />
              {timing.transcriptTs == null && (
                <div className="text-micro text-fg-subtle italic">
                  t0 未定（用户尚未开口）
                </div>
              )}
              <div className="section-label mt-3 mb-1 pt-2 border-t border-border dark:border-border">
                水位 / 会话
              </div>
              <Kv k="连接" v={conn} />
              <Kv k="session state" v={sessionState} />
              <Kv k="session_id" v={sessionId ? truncate(sessionId, 18) : "—"} mono />
              <Kv k="帧数" v={String(debugInfo.framesShown)} />
              <Kv k="音频块" v={String(debugInfo.audioChunks)} />
              <Kv k="帧队列" v={String(debugInfo.queueLen)} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

function Kv({ k, v, mono = false }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-fg-subtle">{k}</span>
      <span className={clsx("text-fg dark:text-fg-dark", mono && "font-mono text-micro")}>{v}</span>
    </div>
  );
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}
