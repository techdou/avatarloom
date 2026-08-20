// TODO: P5 - Blocks API Explorer
import { apiFetch, type BlockDefinition } from "@/lib/api";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";

export default async function BlocksPage() {
  let blocks: BlockDefinition[] = [];
  let error: string | null = null;
  try {
    blocks = await apiFetch<BlockDefinition[]>("/blocks");
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  // 按 category 分组
  const grouped = blocks.reduce<Record<string, BlockDefinition[]>>((acc, b) => {
    (acc[b.category] ||= []).push(b);
    return acc;
  }, {});
  const categories = Object.keys(grouped).sort();

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">模块注册表</h1>
          <p className="page-desc">已注册的 Block 定义，按类别分组</p>
        </div>
      </div>

      {error && <div className="mb-4"><ErrorBanner error={error} hint="请确认 control-api 已启动（默认端口 27810）" /></div>}

      {categories.length === 0 && !error ? (
        <EmptyState
          title="暂无 Block 定义"
          description="Block 定义可通过 Control API 注册。"
        />
      ) : (
        <div className="space-y-6">
          {categories.map((cat) => (
            <div key={cat}>
              <h2 className="section-label mb-2">
                {cat}
              </h2>
              <div className="space-y-1">
                {grouped[cat].map((b) => (
                  <div key={b.id} className="card flex items-center justify-between py-3">
                    <div>
                      <div className="font-mono text-sm">{b.id}</div>
                      <div className="text-xs text-fg-muted mt-0.5">{b.name}</div>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="badge">{b.runtime_type}</span>
                      {b.capabilities && "streaming" in b.capabilities && Boolean(b.capabilities.streaming) && (
                        <span className="badge badge-ok">streaming</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
