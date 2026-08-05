import { apiFetch, type RuntimeProfile } from "@/lib/api";

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
            模块组合与参数档位。当前推荐：<span className="badge badge-accent ml-1">autodl-best</span>
          </p>
        </div>
        <span className="badge">{profiles.length} 个配置</span>
      </div>

      {error && (
        <div className="rounded-xl border border-err/30 bg-err/5 text-err text-sm px-4 py-3 mb-4">
          Control API 连接失败：{error}。请确认 control-api 服务已启动（默认端口 8100）。
        </div>
      )}

      {profiles.length === 0 && !error ? (
        <div className="card text-center text-fg-muted text-sm py-16">
          暂无 Profile。可加载 profiles/ 目录下的 YAML 文件。
        </div>
      ) : (
        <div className="space-y-3">
          {profiles.map((p) => {
            const blockCategories = Object.keys(p.blocks || {});
            const isBest = p.id === "autodl-best";
            return (
              <div key={p.id} className={isBest ? "card card-hover border-accent/40 ring-1 ring-accent/10" : "card card-hover"}>
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
                      <span key={cat} className={local ? "badge font-mono text-[11px]" : "badge badge-warn font-mono text-[11px]"}>
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

      <div className="mt-6">
        <div className="section-label mb-2">内置 Profile（YAML 文件）</div>
        <div className="card text-sm">
          <ul className="text-fg-muted space-y-1.5">
            <li><code className="text-xs">profiles/mock.yaml</code> — 纯 Mock，不依赖任何外部资源</li>
            <li><code className="text-xs">profiles/lite-12gb.yaml</code> — 12GB GPU 单机</li>
            <li><code className="text-xs">profiles/distributed.yaml</code> — 分布式混合</li>
            <li><code className="text-xs">profiles/full-24gb.yaml</code> — 24GB+ GPU 全量</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
