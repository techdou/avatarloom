import { ActiveContextCard } from "@/components/settings/active-context-card";
import { MemoryCard } from "@/components/settings/memory-card";
import { ServiceHealthCard } from "@/components/settings/service-health-card";
import { AccessCard } from "@/components/settings/access-card";

export default function SettingsPage() {
  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">设置</h1>
          <p className="page-desc">运行状态、访问入口与功能配置。</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        {/* 左列：运行上下文 + 访问入口 */}
        <div className="space-y-4">
          <ActiveContextCard />
          <AccessCard />
        </div>

        {/* 右列：服务健康 + 长期记忆 */}
        <div className="space-y-4">
          <ServiceHealthCard />
          <MemoryCard />
        </div>
      </div>

      {/* 下方通栏：内置 Profile + 环境说明 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4 items-start">
        <div className="card">
          <h2 className="mb-3">内置 Profile（YAML 文件）</h2>
          <ul className="text-sm text-fg-muted space-y-1.5">
            <li><code className="text-xs">profiles/mock.yaml</code> — 纯 Mock，不依赖任何外部资源</li>
            <li><code className="text-xs">profiles/lite-12gb.yaml</code> — 12GB GPU 单机</li>
            <li><code className="text-xs">profiles/distributed.yaml</code> — 分布式混合</li>
            <li><code className="text-xs">profiles/full-24gb.yaml</code> — 24GB+ GPU 全量</li>
          </ul>
        </div>

        <div className="card">
          <h2 className="mb-3">环境变量</h2>
          <p className="text-sm text-fg-muted mb-2">
            服务端通过 <code className="text-xs">.env</code> 配置。前端无需 API Key——所有请求经 Runtime Gateway 转发。
          </p>
          <p className="text-xs text-fg-subtle">详见 <code className="text-xs">.env.example</code> 与 <code className="text-xs">.env.autodl.example</code></p>
        </div>
      </div>
    </div>
  );
}
