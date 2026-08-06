export default function SettingsPage() {
  const services = [
    { label: "Control API", value: "http://127.0.0.1:8100", desc: "配置与资产管理" },
    { label: "Runtime Gateway", value: "ws://127.0.0.1:8101/ws/realtime", desc: "实时语音链路" },
    { label: "Studio（本页）", value: "http://127.0.0.1:3000", desc: "前端控制台" },
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">设置</h1>
          <p className="page-desc">服务地址与环境变量说明。</p>
        </div>
      </div>

      <div className="max-w-2xl space-y-4">
        <div className="card">
          <h2 className="mb-4">服务地址</h2>
          <div className="space-y-1">
            {services.map((s) => (
              <div key={s.label} className="flex items-center justify-between py-2.5 border-b border-border last:border-0">
                <div>
                  <div className="text-sm font-medium">{s.label}</div>
                  <div className="text-xs text-fg-muted mt-0.5">{s.desc}</div>
                </div>
                <code className="text-xs bg-bg-subtle border border-border rounded-md px-2 py-1">
                  {s.value}
                </code>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <h2 className="mb-3">环境变量</h2>
          <p className="text-sm text-fg-muted mb-2">
            服务端通过 <code className="text-xs">.env</code> 配置。前端无需 API Key——所有请求经 Runtime Gateway 转发。
          </p>
          <p className="text-xs text-fg-subtle">详见 <code className="text-xs">.env.example</code></p>
        </div>
      </div>
    </div>
  );
}
