"use client";

import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { ChevronUp, ChevronDown } from "lucide-react";
import type { DebugInfo, SessionTiming, ConnState } from "@/hooks/use-realtime-session";

interface DebugDrawerProps {
  conn: ConnState;
  sessionState: string;
  sessionId: string | null;
  debugInfo: DebugInfo;
  timing: SessionTiming;
}

/**
 * 底部调试抽屉——可展开/收起。
 * 展开后显示：管线时间轴（从 session 事件收集的里程碑）+ 实时指标 + session 状态/ID。
 * 收起时只显示一个小条。
 *
 * 注意：timing 的差值需以 transcriptTs 为基准；若用户先开口再被打断，可能 firstDelta
 * 早于 transcriptTs（基线缺失）——此时显示绝对时间，标注 "t=未定"。
 */
export function DebugDrawer({
  conn,
  sessionState,
  sessionId,
  debugInfo,
  timing,
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

  const base = timing.transcriptTs;
  const rel = (ts: number | null) => {
    if (ts == null) return "—";
    if (base == null) return `${ts}`;
    return `+${Math.max(0, ts - base)}ms`;
  };

  return (
    <div className="border-t border-border bg-white dark:bg-bg-subtle dark:border-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 h-9 text-xs font-medium text-fg-muted hover:bg-bg-subtle dark:hover:bg-border/30 transition-colors"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2">
          {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
          调试
        </span>
        <span className="font-mono text-micro text-fg-subtle">
          {debugInfo.framesShown}f · {debugInfo.audioChunks}a · q{debugInfo.queueLen}
        </span>
      </button>

      {open && (
        <div className="px-3 pb-3 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
          {/* 管线时间轴 */}
          <div className="rounded-md border border-border p-2.5 dark:border-border">
            <div className="text-micro font-semibold uppercase tracking-wider text-fg-subtle mb-2">
              管线时间轴
            </div>
            <Timeline label="transcript 完成" value={rel(timing.transcriptTs)} baseline />
            <Timeline label="LLM 首字" value={rel(timing.firstDeltaTs)} />
            <Timeline label="首音 PCM" value={rel(timing.firstPcmTs)} />
            <Timeline label="首帧 JPEG" value={rel(timing.firstFrameTs)} />
            {base == null && (
              <div className="text-micro text-fg-subtle mt-1.5 italic">
                基准 t0 未定（用户尚未开口）；显示绝对 ms 时间戳。
              </div>
            )}
          </div>

          {/* 实时指标 + session */}
          <div className="rounded-md border border-border p-2.5 space-y-1.5 dark:border-border">
            <div className="text-micro font-semibold uppercase tracking-wider text-fg-subtle mb-1">
              实时指标
            </div>
            <Kv k="连接" v={conn} />
            <Kv k="session state" v={sessionState} />
            <Kv k="session_id" v={sessionId ? truncate(sessionId, 18) : "—"} mono />
            <Kv k="帧数" v={String(debugInfo.framesShown)} />
            <Kv k="音频块" v={String(debugInfo.audioChunks)} />
            <Kv k="队列长度" v={String(debugInfo.queueLen)} />
          </div>
        </div>
      )}
    </div>
  );
}

function Timeline({
  label,
  value,
  baseline = false,
}: {
  label: string;
  value: string;
  baseline?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-0.5">
      <span className="flex items-center gap-1.5 text-fg-muted dark:text-fg-muted">
        <span
          className={clsx(
            "w-1.5 h-1.5 rounded-full",
            baseline ? "bg-fg-subtle" : value === "—" ? "bg-border" : "bg-accent"
          )}
        />
        {label}
      </span>
      <span className="font-mono text-fg dark:text-fg-dark">{value}</span>
    </div>
  );
}

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
