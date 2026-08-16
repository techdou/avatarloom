import { gatewayFetch, type GatewayProfilesResponse } from "@/lib/api";
import { SlidersHorizontal } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";

/**
 * 运行时配置列表——数据源是 gateway /profiles（profiles/ 目录的 yaml 概要）。
 * 这是 session.start 真实装配的来源；control-api DB 里的 RuntimeProfile 表
 * 尚无注册流程，不作为 UI 数据源。
 */
export default async function ProfilesPage() {
  let data: GatewayProfilesResponse | null = null;
  let error: string | null = null;
  try {
    data = await gatewayFetch<GatewayProfilesResponse>("/profiles");
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }
  const profiles = data?.profiles ?? [];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">运行时配置</h1>
          <p className="page-desc">
            模块组合与参数档位。当前推荐：<span className="badge badge-accent ml-1">autodl-best</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="badge">默认 {data?.default ?? "—"}</span>
          <span className="badge">{profiles.length} 个配置</span>
        </div>
      </div>

      {error && (
        <div className="mb-4">
          <ErrorBanner error={error} hint="请确认 Runtime Gateway 服务已启动（默认端口 8101）" />
        </div>
      )}

      {profiles.length === 0 && !error ? (
        <EmptyState
          icon={<SlidersHorizontal className="w-5 h-5" />}
          title="暂无运行时配置"
          description="在 profiles/ 目录下放置 RuntimeProfile YAML 即可注册配置。"
        />
      ) : (
        <div className="space-y-3">
          {profiles.map((p) => {
            const blockCategories = Object.keys(p.blocks || {});
            const isBest = p.id === "autodl-best";
            const isDefault = p.id === data?.default;
            return (
              <div key={p.id} className={isBest ? "card card-hover ring-1 ring-accent/30" : "card card-hover"}>
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div className="flex items-center gap-2">
                    <div className="font-medium">{p.name}</div>
                    {isBest && <span className="badge badge-accent">推荐</span>}
                    {isDefault && <span className="badge">默认</span>}
                    {p.memory && <span className="badge">memory</span>}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="badge">{blockCategories.length} blocks</span>
                    <span className="text-xs text-fg-subtle font-mono">{p.id}</span>
                  </div>
                </div>
                {p.description && (
                  <div className="text-sm text-fg-muted mb-3 whitespace-pre-line">{p.description}</div>
                )}
                <div className="flex flex-wrap gap-1.5">
                  {blockCategories.map((cat) => {
                    const blockRef = p.blocks[cat];
                    const local = blockRef?.deployment !== "remote";
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
