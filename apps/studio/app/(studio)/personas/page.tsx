import { apiFetch, type Persona } from "@/lib/api";
import Link from "next/link";
import { UserCircle2 } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";

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
        <div className="mb-4">
          <ErrorBanner error={error} hint="请确认 control-api 服务已启动（默认端口 8100）" />
        </div>
      )}

      {personas.length === 0 && !error ? (
        <EmptyState
          icon={<UserCircle2 className="w-5 h-5" />}
          title="暂无人设"
          description="人设定义数字人的性格、语气与回复风格。"
          action={{ label: "创建第一个 Persona", href: "/personas/new" }}
        />
      ) : (
        <div className="space-y-2">
          {personas.map((p) => (
            <Link key={p.id} href={`/personas/${p.id}`} className="card card-hover block">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg bg-bg-subtle text-fg-muted flex items-center justify-center text-sm font-semibold dark:bg-border/30">
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
                <div className="text-sm text-fg-muted mt-2 line-clamp-2 whitespace-pre-wrap">{p.prompt}</div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
