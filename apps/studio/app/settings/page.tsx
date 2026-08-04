export default function SettingsPage() {
  return (
    <div>
      <h1 className="mb-6">Settings</h1>
      <div className="card max-w-2xl">
        <h2 className="mb-4">服务地址</h2>
        <div className="space-y-3 text-sm">
          <div className="flex justify-between border-b border-border pb-2">
            <span className="text-fg-muted">Control API</span>
            <code className="text-xs">http://127.0.0.1:8100</code>
          </div>
          <div className="flex justify-between border-b border-border pb-2">
            <span className="text-fg-muted">Runtime Gateway</span>
            <code className="text-xs">ws://127.0.0.1:8101/ws/realtime</code>
          </div>
          <div className="flex justify-between">
            <span className="text-fg-muted">Studio (本页)</span>
            <code className="text-xs">http://127.0.0.1:3000</code>
          </div>
        </div>
      </div>

      <div className="card max-w-2xl mt-4">
        <h2 className="mb-4">环境变量</h2>
        <p className="text-sm text-fg-muted mb-2">
          服务端通过 <code>.env</code> 配置。前端无需 API Key——所有请求经 Runtime Gateway 转发。
        </p>
        <p className="text-xs text-fg-subtle">
          详见 <code>.env.example</code>
        </p>
      </div>
    </div>
  );
}
