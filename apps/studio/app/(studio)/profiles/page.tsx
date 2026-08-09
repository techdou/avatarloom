import { apiFetch, type RuntimeProfile } from "@/lib/api";
import { SlidersHorizontal } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";

export default async function ProfilesPage() {
  let profiles: RuntimeProfile[] = [];
  let error: string | null = null;
  try {
    profiles = await apiFetch<RuntimeProfile[]>("/profiles");
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">运行时配置</h1>
          <p className="page-desc">
            模块组合与参数档位。开箱默认：<span className="badge badge-accent ml-1">mock</span>
          </p>
        </div>
        <span className="badge">{profiles.length} 个配置</span>
      </div>

      {error && (
        <div className="mb-4">
          <ErrorBanner error={error} hint="请确认 control-api 服务已启动（默认端口 8100）" />
        </div>
      )}

      {profiles.length === 0 && !error ? (
        <EmptyState
          icon={<SlidersHorizontal className="w-5 h-5" />}
          title="暂无运行时配置"
          description="可加载 profiles/ 目录下的 YAML 文件注册配置。"
        />
      ) : (
        <div className="space-y-3">
          {profiles.map((p) => {
            const blockCategories = Object.keys(p.blocks || {});
            const isBest = p.id === "mock";
            return (
              <div key={p.id} className={isBest ? "card card-hover ring-1 ring-accent/30" : "card card-hover"}>
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div className="flex items-center gap-2">
                    <div className="font-medium">{p.name}</div>
                    {isBest && <span className="badge badge-accent">推荐</span>}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="badge">{blockCategories.length} blocks</span>
                    <span className="text-xs text-fg-subtle font-mono">{p.id}</span>
                  </div>
                </div>
                {p.description && (
                  <div className="text-sm text-fg-muted mb-3">{p.description}</div>
                )}
                <div className="flex flex-wrap gap-1.5">
                  {blockCategories.map((cat) => {
                    const blockRef = (p.blocks as Record<string, { id?: string }>)[cat];
                    const local = (p.blocks as Record<string, { deployment?: string }>)[cat]?.deployment !== "remote";
                    return (
                      <span key={cat} className={local ? "badge font-mono text-micro" : "badge badge-warn font-mono text-micro"}>
                        {cat}: {blockRef?.id || "?"}
                      </span>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
