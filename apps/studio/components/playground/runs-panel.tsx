"use client";

import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { Run, RunMetrics } from "@/lib/api";
import { PipelineTimeline } from "./pipeline-timeline";

/**
 * 右侧滑入的运行记录面板。
 * - 从 /api/control/runs 拉取最近 10 条
 * - 每条：状态 badge + 4 指标 grid（首字/首音/首帧/总时长）+ 对话摘要
 * - 点击展开 PipelineTimeline
 */
export function RunsPanel({ onClose }: { onClose: () => void }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetch("/api/control/runs?limit=10")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`API ${r.status}`))))
      .then((list: Run[] | { items?: Run[] }) => {
        if (!alive) return;
        // 兼容裸数组或 { items: [] }
        const arr = Array.isArray(list) ? list : (list?.items ?? []);
        setRuns(arr);
        setErr(null);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden />
      <aside className="absolute right-0 top-0 bottom-0 w-full max-w-md bg-white dark:bg-bg-subtle border-l border-border dark:border-border shadow-pop flex flex-col animate-[slideIn_.18s_ease-out]">
        <div className="px-4 h-14 border-b border-border flex items-center justify-between dark:border-border">
          <div className="text-sm font-semibold">运行记录</div>
          <button onClick={onClose} className="btn btn-sm btn-ghost" aria-label="关闭">
            关闭
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {loading && (
            <div className="text-sm text-fg-muted dark:text-fg-muted py-6 text-center">
              载入中…
            </div>
          )}
          {err && (
            <div className="rounded-lg border border-err/30 bg-err/5 text-err text-xs px-3 py-2">
              载入失败：{err}
            </div>
          )}
          {!loading && !err && runs.length === 0 && (
            <div className="text-sm text-fg-muted dark:text-fg-muted py-6 text-center">
              暂无运行记录。
            </div>
          )}
          {runs.map((run) => (
            <RunRow
              key={run.id}
              run={run}
              expanded={expanded === run.id}
              onToggle={() =>
                setExpanded((cur) => (cur === run.id ? null : run.id))
              }
            />
          ))}
        </div>
      </aside>
    </div>
  );
}

function RunRow({
  run,
  expanded,
  onToggle,
}: {
  run: Run;
  expanded: boolean;
  onToggle: () => void;
}) {
  const metrics = (run.metrics || {}) as RunMetrics;
  const startedAt = new Date(run.started_at);
  return (
    <div className="card p-0 overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-bg-subtle dark:hover:bg-border/30 transition-colors"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-fg-subtle shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-fg-subtle shrink-0" />
        )}
        <span className={clsx("badge text-[10px] shrink-0", statusBadge(run.status))}>
          {run.status}
        </span>
        <span className="text-xs text-fg-muted truncate dark:text-fg-muted">
          {run.user_text || "(无输入)"}
        </span>
        <span className="ml-auto text-[10px] text-fg-subtle font-mono shrink-0">
          {startedAt.toLocaleTimeString()}
        </span>
      </button>

      {/* 4 指标 grid */}
      <div className="grid grid-cols-4 gap-1.5 px-3 pb-2.5 text-center">
        <Metric label="首字" valueMs={metrics.first_text_ms} />
        <Metric label="首音" valueMs={metrics.first_audio_ms} />
        <Metric label="首帧" valueMs={metrics.first_frame_ms} />
        <Metric label="总时长" valueMs={metrics.total_duration_ms} />
      </div>

      {expanded && (
        <div className="border-t border-border px-3 py-3 dark:border-border">
          <div className="text-[11px] text-fg-muted mb-2 dark:text-fg-muted">管道时序</div>
          <PipelineTimeline metrics={metrics} />
          {(run.user_text || run.assistant_text) && (
            <div className="mt-3 space-y-1.5">
              {run.user_text && (
                <div className="text-xs">
                  <span className="text-fg-subtle">你：</span>
                  <span className="text-fg dark:text-[#ededf2]">{run.user_text}</span>
                </div>
              )}
              {run.assistant_text && (
                <div className="text-xs">
                  <span className="text-fg-subtle">小灵：</span>
                  <span className="text-fg dark:text-[#ededf2]">{run.assistant_text}</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Metric({ label, valueMs }: { label: string; valueMs?: number | null }) {
  const has = valueMs != null;
  return (
    <div className="rounded-md bg-bg-subtle dark:bg-border/20 py-1.5">
      <div className="text-[10px] text-fg-subtle">{label}</div>
      <div className={clsx("text-xs font-mono mt-0.5", has ? "text-fg dark:text-[#ededf2]" : "text-fg-subtle")}>
        {has ? `${valueMs}ms` : "—"}
      </div>
    </div>
  );
}

function statusBadge(status: string): string {
  if (status === "completed") return "badge-ok";
  if (status === "interrupted" || status === "cancelled") return "badge-warn";
  if (status === "error") return "badge-err";
  return "";
}
