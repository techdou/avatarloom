// TODO: P5 - Blocks API Explorer
import { apiFetch, type BlockDefinition } from "@/lib/api";

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
      <h1 className="mb-6">Block Registry</h1>

      {error && (
        <div className="card border-err/40 text-err text-sm mb-4">
          Control API 连接失败：{error}
        </div>
      )}

      {categories.length === 0 && !error ? (
        <div className="card text-center text-fg-muted text-sm py-12">
          暂无 Block 定义。可通过 Control API 注册。
        </div>
      ) : (
        <div className="space-y-6">
          {categories.map((cat) => (
            <div key={cat}>
              <h2 className="text-sm font-medium text-fg-muted mb-2 uppercase tracking-wide">
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
                      <span className="text-fg-subtle">v{b.version}</span>
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
