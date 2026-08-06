import { clsx } from "clsx";
import type { RunMetrics } from "@/lib/api";

/**
 * 管道事件流时序——transcript → llm → tts → avatar → done 的里程碑。
 * 从 runs/[id]/page.tsx 抽取，供 Run 详情页和 RunsPanel 复用。
 */
export function PipelineTimeline({ metrics }: { metrics: RunMetrics }) {
  const stages = [
    { key: "transcript", label: "用户语音识别", atMs: 0, ready: true },
    { key: "llm", label: "LLM 首字", atMs: metrics.first_text_ms, ready: metrics.first_text_ms != null },
    { key: "tts", label: "TTS 首音", atMs: metrics.first_audio_ms, ready: metrics.first_audio_ms != null },
    { key: "avatar", label: "Avatar 首帧", atMs: metrics.first_frame_ms, ready: metrics.first_frame_ms != null },
    {
      key: "done",
      label: "完成",
      atMs: metrics.total_duration_ms,
      ready: metrics.total_duration_ms != null,
    },
  ];
  return (
    <ol className="relative">
      {/* 竖线 */}
      <div className="absolute left-[7px] top-1 bottom-1 w-px bg-border dark:bg-border" aria-hidden />
      {stages.map((s, i) => (
        <li key={s.key} className="relative pl-7 pb-4 last:pb-0">
          {/* 节点 */}
          <span
            className={clsx(
              "absolute left-0 top-0.5 w-3.5 h-3.5 rounded-full border-2 border-white dark:border-bg-subtle",
              s.ready ? (s.key === "done" ? "bg-fg-subtle" : "bg-accent") : "bg-border dark:bg-border"
            )}
          />
          <div className="flex items-center justify-between gap-3">
            <span className={clsx("text-sm", s.ready ? "text-fg dark:text-fg-dark" : "text-fg-subtle")}>
              <span className="text-fg-subtle font-mono text-xs mr-2">{String(i + 1).padStart(2, "0")}</span>
              {s.label}
            </span>
            <span className="text-xs font-mono text-fg-muted dark:text-fg-muted">
              {s.ready && s.atMs != null ? `+${s.atMs}ms` : "—"}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
}
