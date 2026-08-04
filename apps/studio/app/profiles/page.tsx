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
      <h1 className="mb-6">Runtime Profiles</h1>

      {error && (
        <div className="card border-err/40 text-err text-sm mb-4">
          Control API 连接失败：{error}
        </div>
      )}

      {profiles.length === 0 && !error ? (
        <div className="card text-center text-fg-muted text-sm py-12">
          暂无 Profile。可加载 profiles/ 目录下的 YAML 文件。
        </div>
      ) : (
        <div className="space-y-2">
          {profiles.map((p) => {
            const blockCategories = Object.keys(p.blocks || {});
            return (
              <div key={p.id} className="card">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <div className="font-medium">{p.name}</div>
                    <div className="text-xs text-fg-muted">{p.id}</div>
                  </div>
                  <span className="badge">{blockCategories.length} blocks</span>
                </div>
                {p.description && (
                  <div className="text-sm text-fg-muted mb-2">{p.description}</div>
                )}
                <div className="flex flex-wrap gap-1">
                  {blockCategories.map((cat) => {
                    const blockRef = (p.blocks as Record<string, { id?: string }>)[cat];
                    return (
                      <span key={cat} className="badge font-mono text-xs">
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

      <div className="mt-6 card text-sm">
        <h3 className="mb-2">内置 Profile（YAML 文件）</h3>
        <ul className="text-fg-muted space-y-1">
          <li><code className="text-xs">profiles/mock.yaml</code> — 纯 Mock，不依赖任何外部资源</li>
          <li><code className="text-xs">profiles/lite-12gb.yaml</code> — 12GB GPU 单机</li>
          <li><code className="text-xs">profiles/distributed.yaml</code> — 分布式混合</li>
          <li><code className="text-xs">profiles/full-24gb.yaml</code> — 24GB+ GPU 全量</li>
        </ul>
      </div>
    </div>
  );
}
