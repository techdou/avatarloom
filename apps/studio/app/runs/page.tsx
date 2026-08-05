import Link from "next/link";
import { apiFetch, type Run } from "@/lib/api";

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
      <h1 className="mb-6">Runs</h1>
      {error && (
        <div className="card border-err/40 text-err text-sm mb-4">Control API 连接失败：{error}</div>
      )}
      {runs.length === 0 && !error ? (
        <div className="card text-center text-fg-muted text-sm py-12">
          暂无 Run 记录。每次对话会产生一个 Run，含事件流、性能指标、产物。
        </div>
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
                    <span className={`badge ${r.status === "completed" ? "badge-ok" : r.status === "interrupted" ? "badge-warn" : "badge-err"}`}>
                      {r.status}
                    </span>
                    <span className="text-fg-subtle">{new Date(r.started_at).toLocaleString()}</span>
                  </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs text-fg-muted">
                  <Metric label="首字" value={m.first_text_ms != null ? `${m.first_text_ms}ms` : "—"} />
                  <Metric label="首音" value={m.first_audio_ms != null ? `${m.first_audio_ms}ms` : "—"} />
                  <Metric label="首帧" value={m.first_frame_ms != null ? `${m.first_frame_ms}ms` : "—"} />
                  <Metric label="总时长" value={m.total_duration_ms != null ? `${m.total_duration_ms}ms` : "—"} />
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-fg-subtle">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}
