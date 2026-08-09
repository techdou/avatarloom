import { ActiveContextCard } from "@/components/settings/active-context-card";
import { MemoryManager } from "@/components/settings/memory-manager";
import { BlocksHealthCard } from "@/components/settings/blocks-health-card";
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

        {/* 右列：服务健康 + 组件健康 */}
        <div className="space-y-4">
          <ServiceHealthCard />
          <BlocksHealthCard />
        </div>
      </div>

      {/* 下方通栏：长期记忆管理 + 内置 Profile */}
      <div className="space-y-4 mt-4">
        <MemoryManager />

        <div className="card">
          <h2 className="mb-3">内置 Profile（Control API 初始化模板）</h2>
          <ul className="text-sm text-fg-muted space-y-1.5">
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
