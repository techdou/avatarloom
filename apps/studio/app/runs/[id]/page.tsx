import Link from "next/link";
import { notFound } from "next/navigation";
import { clsx } from "clsx";
import { apiFetch, type Run, type RunMetrics, type Artifact } from "@/lib/api";

interface PageProps {
  params: { id: string };
}

async function getRun(id: string): Promise<Run | null> {
  try {
    return await apiFetch<Run>(`/runs/${id}`);
  } catch {
    return null;
  }
}

async function getArtifacts(runId: string): Promise<Artifact[]> {
  try {
    return await apiFetch<Artifact[]>(`/artifacts?run_id=${encodeURIComponent(runId)}`);
  } catch {
    return [];
  }
}

/** Run 详情页——单轮对话的指标、事件流时序、对话回放、产物。 */
export default async function RunDetailPage({ params }: PageProps) {
  const run = await getRun(params.id);
  if (!run) notFound();
  const artifacts = await getArtifacts(run.id);
  const metrics = (run.metrics || {}) as RunMetrics;

  const startedAt = new Date(run.started_at);
  const endedAt = run.ended_at ? new Date(run.ended_at) : null;

  return (
    <div>
      {/* 顶部导航 */}
      <div className="flex items-center gap-3 mb-5 text-sm">
        <Link href="/runs" className="text-fg-muted hover:text-fg dark:text-fg-muted dark:hover:text-fg">
          ← Runs
        </Link>
        <span className="text-fg-subtle">/</span>
        <span className="font-mono text-xs">{run.id}</span>
      </div>

      {/* 标题 + 状态 */}
      <div className="page-header">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="page-title">Run 详情</h1>
            <span className={clsx("badge", statusBadge(run.status))}>{run.status}</span>
            {metrics.cancelled && <span className="badge badge-warn">已打断</span>}
          </div>
          <p className="page-desc">
            {startedAt.toLocaleString()}
            {endedAt && (
              <span className="ml-2 font-mono">
                · 耗时 {formatDuration(endedAt.getTime() - startedAt.getTime())}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href={`/sessions#${run.session_id}`} className="btn btn-sm">
            所属会话
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左 2/3：指标 + 管道时序 + 对话 */}
        <div className="lg:col-span-2 space-y-6">
          {/* 延迟指标条形图 */}
          <section className="card">
            <h2 className="mb-1">延迟指标</h2>
            <p className="text-xs text-fg-muted mb-4 dark:text-fg-muted">
              从 Run 开始计的相对毫秒数。柱长按总时长归一化。
            </p>
            <div className="space-y-3">
              <MetricBar label="首字（LLM）" valueMs={metrics.first_text_ms} totalMs={metrics.total_duration_ms} tone="accent" />
              <MetricBar label="首音（TTS）" valueMs={metrics.first_audio_ms} totalMs={metrics.total_duration_ms} tone="warn" />
              <MetricBar label="首帧（Avatar）" valueMs={metrics.first_frame_ms} totalMs={metrics.total_duration_ms} tone="ok" />
              <MetricBar label="总时长" valueMs={metrics.total_duration_ms} totalMs={metrics.total_duration_ms} tone="muted" />
            </div>
          </section>

          {/* 管道事件流时序 */}
          <section className="card">
            <h2 className="mb-1">管道时序</h2>
            <p className="text-xs text-fg-muted mb-4 dark:text-fg-muted">
              transcript → llm → tts → avatar → done 的关键里程碑。
            </p>
            <PipelineTimeline metrics={metrics} />
          </section>

          {/* 对话回放 */}
          {(run.user_text || run.assistant_text) && (
            <section className="card">
              <h2 className="mb-3">对话内容</h2>
              <div className="space-y-3">
                {run.user_text && (
                  <TranscriptBubble role="user" text={run.user_text} />
                )}
                {run.assistant_text && (
                  <TranscriptBubble role="assistant" text={run.assistant_text} />
                )}
              </div>
            </section>
          )}
        </div>

        {/* 右 1/3：可靠性 + 产物 */}
        <div className="space-y-6">
          <section className="card">
            <h2 className="mb-3">可靠性</h2>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <Stat label="中断次数" value={metrics.interruptions ?? 0} tone={(metrics.interruptions ?? 0) > 0 ? "warn" : "muted"} />
              <Stat label="降级次数" value={metrics.degradations ?? 0} tone={(metrics.degradations ?? 0) > 0 ? "warn" : "muted"} />
              <Stat label="错误数" value={metrics.errors ?? 0} tone={(metrics.errors ?? 0) > 0 ? "err" : "muted"} />
              <Stat label="Avatar 帧数" value={metrics.avatar_frames ?? 0} tone="muted" />
            </dl>
            {metrics.degraded_blocks && Object.keys(metrics.degraded_blocks).length > 0 && (
              <div className="mt-4 pt-3 border-t border-border dark:border-border">
                <div className="text-xs text-fg-muted mb-2 dark:text-fg-muted">降级路径</div>
                <div className="space-y-1">
                  {Object.entries(metrics.degraded_blocks).map(([from, to]) => (
                    <div key={from} className="text-xs font-mono flex items-center gap-1.5">
                      <span className="text-fg-muted">{from}</span>
                      <span className="text-fg-subtle">→</span>
                      <span className="text-warn">{String(to)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {metrics.block_versions && Object.keys(metrics.block_versions).length > 0 && (
              <div className="mt-4 pt-3 border-t border-border dark:border-border">
                <div className="text-xs text-fg-muted mb-2 dark:text-fg-muted">模块版本</div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(metrics.block_versions).map(([name, ver]) => (
                    <span key={name} className="badge font-mono text-[10px]">
                      {name}@{String(ver)}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </section>

          {/* 产物 */}
          <section className="card">
            <h2 className="mb-3">产物</h2>
            {run.run_dir && (
              <div className="text-xs text-fg-subtle font-mono mb-3 break-all">
                {run.run_dir}
              </div>
            )}
            {artifacts.length === 0 ? (
              <div className="text-sm text-fg-muted dark:text-fg-muted py-2">
                暂无产物记录。
              </div>
            ) : (
              <div className="space-y-2">
                {artifacts.map((a) => (
                  <ArtifactRow key={a.id} artifact={a} />
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 子组件
// ---------------------------------------------------------------------------

const TONES: Record<string, string> = {
  accent: "bg-accent",
  warn: "bg-warn",
  ok: "bg-ok",
  muted: "bg-fg-subtle",
};

function MetricBar({
  label,
  valueMs,
  totalMs,
  tone,
}: {
  label: string;
  valueMs: number | null | undefined;
  totalMs: number | null | undefined;
  tone: "accent" | "warn" | "ok" | "muted";
}) {
  const hasValue = valueMs != null;
  const total = totalMs && totalMs > 0 ? totalMs : undefined;
  // 归一化宽度：相对于总时长，至少留出 1% 让小值可见
  const pct = hasValue && total ? Math.max(1, Math.min(100, (valueMs! / total) * 100)) : 0;
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1.5">
        <span className="text-fg-muted dark:text-fg-muted">{label}</span>
        <span className="font-mono text-fg dark:text-[#ededf2]">
          {hasValue ? `${valueMs}ms` : "—"}
        </span>
      </div>
      <div className="h-2 rounded-full bg-border/40 overflow-hidden dark:bg-border/30">
        {hasValue && (
          <div
            className={clsx("h-full rounded-full transition-all", TONES[tone])}
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
    </div>
  );
}

function PipelineTimeline({ metrics }: { metrics: RunMetrics }) {
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
            <span className={clsx("text-sm", s.ready ? "text-fg dark:text-[#ededf2]" : "text-fg-subtle")}>
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

function TranscriptBubble({ role, text }: { role: "user" | "assistant"; text: string }) {
  const isUser = role === "user";
  return (
    <div className={clsx("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={clsx(
          "max-w-[88%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
          isUser
            ? "bg-accent-soft text-fg rounded-br-md dark:bg-accent/15"
            : "bg-bg-subtle border border-border rounded-bl-md dark:bg-border/20 dark:border-border"
        )}
      >
        <div className="text-[10px] text-fg-subtle mb-1">{isUser ? "你" : "小灵"}</div>
        <div className="whitespace-pre-wrap break-words">{text}</div>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone: "warn" | "err" | "muted";
}) {
  const toneClass = {
    warn: "text-warn",
    err: "text-err",
    muted: "text-fg dark:text-[#ededf2]",
  }[tone];
  return (
    <div>
      <dt className="text-xs text-fg-subtle">{label}</dt>
      <dd className={clsx("text-lg font-semibold font-mono mt-0.5", toneClass)}>{value}</dd>
    </div>
  );
}

function ArtifactRow({ artifact }: { artifact: Artifact }) {
  const isVideo = artifact.mime_type?.startsWith("video/");
  const isAudio = artifact.mime_type?.startsWith("audio/");
  return (
    <div className="border border-border rounded-md p-2.5 dark:border-border">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-xs font-medium truncate">{artifact.path.split(/[\\/]/).pop() || artifact.path}</span>
        <span className="badge text-[10px] shrink-0">{artifact.kind}</span>
      </div>
      <div className="flex items-center gap-2 text-[11px] text-fg-subtle font-mono">
        <span>{artifact.mime_type || "unknown"}</span>
        {artifact.size_bytes != null && (
          <span>· {formatBytes(artifact.size_bytes)}</span>
        )}
      </div>
      {/* 注：暂无 artifact 文件流端点；当 kind 为媒体且后端提供时此处预留回放位。
          run_dir 是服务端工作区路径，前端不可直接访问。 */}
      {(isVideo || isAudio) && (
        <div className="mt-2 text-[11px] text-fg-subtle italic">
          {isVideo ? "视频" : "音频"}回放需通过产物文件端点访问（暂未开放）。
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function statusBadge(status: string): string {
  if (status === "completed") return "badge-ok";
  if (status === "interrupted" || status === "cancelled") return "badge-warn";
  if (status === "error") return "badge-err";
  return "";
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return `${m}m${rem}s`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}
