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
      <div className="flex items-center justify-between mb-6">
        <h1>Personas</h1>
        <Link href="/personas/new" className="btn btn-primary">新建</Link>
      </div>

      {error && (
        <div className="card border-err/40 text-err text-sm mb-4">
          Control API 连接失败：{error}。请确认 control-api 服务已启动（默认端口 8100）。
        </div>
      )}

      {personas.length === 0 && !error ? (
        <div className="card text-center text-fg-muted text-sm py-12">
          暂无 Persona。点击「新建」创建第一个数字人人设。
        </div>
      ) : (
        <div className="space-y-2">
          {personas.map((p) => (
            <Link key={p.id} href={`/personas/${p.id}`} className="card block hover:border-accent">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-fg-muted mt-0.5">
                    {p.label && <span className="badge mr-2">{p.label}</span>}
                    v{p.version}
                  </div>
                </div>
                <div className="text-xs text-fg-subtle">{p.id}</div>
              </div>
              {p.prompt && (
                <div className="text-sm text-fg-muted mt-2 line-clamp-2">{p.prompt}</div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
