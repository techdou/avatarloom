import Link from "next/link";

export default function AvatarsPage() {
  return (
    <div>
      <h1 className="mb-6">Avatars</h1>
      <div className="card text-center text-fg-muted text-sm py-12">
        <p>Avatar 管理面板（v0.1 简化版）。</p>
        <p className="mt-2">
          前往 <Link href="/playground" className="underline">Realtime Playground</Link> 直接体验数字人对话。
        </p>
      </div>
    </div>
  );
}
