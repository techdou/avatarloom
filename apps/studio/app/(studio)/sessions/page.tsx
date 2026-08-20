import { apiFetch, type Session } from "@/lib/api";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";

export default async function SessionsPage() {
  let sessions: Session[] = [];
  let error: string | null = null;
  try {
    sessions = await apiFetch<Session[]>("/sessions");
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">会话</h1>
          <p className="page-desc">每次连接 Playground 产生一个会话</p>
        </div>
      </div>
      {error && <div className="mb-4"><ErrorBanner error={error} hint="请确认 control-api 已启动（默认端口 27810）" /></div>}
      {sessions.length === 0 && !error ? (
        <EmptyState
          title="暂无会话记录"
          description="打开实时对话开始语音交互后，会话会在此显示。"
          action={{ label: "进入实时对话", href: "/playground" }}
        />
      ) : (
        <div className="space-y-1">
          {sessions.map((s) => (
            <div
              key={s.id}
              id={s.id}
              className="card flex items-center justify-between py-3 text-sm scroll-mt-20"
            >
              <div className="font-mono text-xs">{s.id}</div>
              <div className="flex items-center gap-3 text-xs text-fg-muted">
                <span className="badge">{s.status}</span>
                <span>{new Date(s.started_at).toLocaleString()}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
