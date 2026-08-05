import { apiFetch, type Persona } from "@/lib/api";
import Link from "next/link";

export default async function PersonasPage() {
  let personas: Persona[] = [];
  let error: string | null = null;
  try {
    personas = await apiFetch<Persona[]>("/personas");
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">人设</h1>
          <p className="page-desc">数字人的性格、语气与回复风格。</p>
        </div>
        <Link href="/personas/new" className="btn btn-primary">新建</Link>
      </div>

      {error && (
        <div className="rounded-xl border border-err/30 bg-err/5 text-err text-sm px-4 py-3 mb-4">
          Control API 连接失败：{error}。请确认 control-api 服务已启动（默认端口 8100）。
        </div>
      )}

      {personas.length === 0 && !error ? (
        <div className="card text-center text-fg-muted text-sm py-16">
          暂无 Persona。点击「新建」创建第一个数字人人设。
        </div>
      ) : (
        <div className="space-y-2.5">
          {personas.map((p) => (
            <Link key={p.id} href={`/personas/${p.id}`} className="card card-hover block">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg bg-accent-soft text-accent flex items-center justify-center text-sm font-semibold">
                    {p.name.slice(0, 1)}
                  </div>
                  <div>
                    <div className="font-medium">{p.name}</div>
                    <div className="text-xs text-fg-muted mt-0.5">
                      {p.label && <span className="badge mr-1.5">{p.label}</span>}
                      v{p.version}
                    </div>
                  </div>
                </div>
                <div className="text-xs text-fg-subtle font-mono">{p.id}</div>
              </div>
              {p.prompt && (
                <div className="text-sm text-fg-muted mt-2.5 line-clamp-2">{p.prompt}</div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
