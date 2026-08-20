import Link from "next/link";
import { apiFetch, type Run } from "@/lib/api";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";

export default async function RunsPage() {
  let runs: Run[] = [];
  let error: string | null = null;
  try {
    runs = await apiFetch<Run[]>("/runs");
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">运行记录</h1>
          <p className="page-desc">每轮对话的录制与指标</p>
        </div>
      </div>
      {error && <div className="mb-4"><ErrorBanner error={error} hint="请确认 control-api 已启动（默认端口 27810）" /></div>}
      {runs.length === 0 && !error ? (
        <EmptyState
          title="暂无运行记录"
          description="每次对话会产生一个 Run，含事件流、性能指标与产物。"
          action={{ label: "进入实时对话", href: "/playground" }}
        />
      ) : (
        <div className="space-y-2">
          {runs.map((r) => {
            const m = (r.metrics || {}) as Record<string, number | null | undefined>;
            return (
              <Link
                key={r.id}
                href={`/runs/${r.id}`}
                className="card card-hover block text-sm"
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="font-mono text-xs">{r.id}</div>
                  <div className="flex items-center gap-2 text-xs">
                    <span className={`badge ${statusBadge(r.status)}`}>
                      {r.status}
                    </span>
                    <span className="text-fg-subtle">{new Date(r.started_at).toLocaleString()}</span>
                  </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs text-fg-muted">
                  <Metric label="首字" value={m.first_text_ms != null ? `${m.first_text_ms}ms` : "—"} />
                  <Metric label="总时长" value={m.total_duration_ms != null ? `${m.total_duration_ms}ms` : "—"} />
                  <Metric className="hidden sm:block" label="首音" value={m.first_audio_ms != null ? `${m.first_audio_ms}ms` : "—"} />
                  <Metric className="hidden sm:block" label="首帧" value={m.first_frame_ms != null ? `${m.first_frame_ms}ms` : "—"} />
                </div>
                {r.user_text && (
                  <div className="mt-2 text-xs"><span className="text-fg-subtle">用户：</span>{r.user_text}</div>
                )}
                {r.assistant_text && (
                  <div className="text-xs"><span className="text-fg-subtle">助手：</span>{r.assistant_text}</div>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

function statusBadge(status: string): string {
  if (status === "completed") return "badge-ok";
  if (status === "interrupted" || status === "cancelled") return "badge-warn";
  if (status === "error") return "badge-err";
  if (status === "running") return "badge-accent";
  return "";
}

function Metric({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className={className}>
      <div className="text-fg-subtle">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}
