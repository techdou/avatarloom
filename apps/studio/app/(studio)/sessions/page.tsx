import { apiFetch, type Session } from "@/lib/api";

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
      <h1 className="mb-6">Sessions</h1>
      {error && (
        <div className="card border-err/40 text-err text-sm mb-4">Control API 连接失败：{error}</div>
      )}
      {sessions.length === 0 && !error ? (
        <div className="card text-center text-fg-muted text-sm py-12">
          暂无会话记录。打开 Playground 开始对话后会在此显示。
        </div>
      ) : (
        <div className="space-y-1">
          {sessions.map((s) => (
            <div key={s.id} className="card flex items-center justify-between py-3 text-sm">
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
