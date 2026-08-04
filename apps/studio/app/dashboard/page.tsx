import Link from "next/link";
import { apiFetch, type Persona, type BlockDefinition, type RuntimeProfile } from "@/lib/api";

async function getStats() {
  const safe = async <T,>(p: Promise<T[]>): Promise<T[]> => {
    try { return await p; } catch { return []; }
  };
  const [personas, blocks, profiles] = await Promise.all([
    safe(apiFetch<Persona[]>("/personas")),
    safe(apiFetch<BlockDefinition[]>("/blocks")),
    safe(apiFetch<RuntimeProfile[]>("/profiles")),
  ]);
  return { personas, blocks, profiles };
}

export default async function DashboardPage() {
  const { personas, blocks, profiles } = await getStats();

  const stats = [
    { label: "Personas", value: personas.length, href: "/personas" },
    { label: "Block Definitions", value: blocks.length, href: "/blocks" },
    { label: "Runtime Profiles", value: profiles.length, href: "/profiles" },
  ];

  return (
    <div>
      <h1 className="mb-1">Dashboard</h1>
      <p className="text-sm text-fg-muted mb-6">
        AvatarLoom 灵构——模块化实时数字人运行平台
      </p>

      <div className="grid grid-cols-3 gap-4 mb-8">
        {stats.map((s) => (
          <Link key={s.label} href={s.href} className="card hover:border-accent transition-colors">
            <div className="text-sm text-fg-muted">{s.label}</div>
            <div className="text-3xl font-semibold mt-1">{s.value}</div>
          </Link>
        ))}
      </div>

      <div className="card">
        <h2 className="mb-3">快速开始</h2>
        <ol className="text-sm space-y-2 text-fg-muted list-decimal pl-5">
          <li>前往 <Link href="/personas" className="underline">Personas</Link> 创建或查看数字人人设</li>
          <li>在 <Link href="/profiles" className="underline">Runtime Profiles</Link> 选择积木组合</li>
          <li>打开 <Link href="/playground" className="underline">Realtime Playground</Link> 开始对话</li>
          <li>在 <Link href="/runs" className="underline">Runs</Link> 查看每轮对话的录制和指标</li>
        </ol>
      </div>

      <div className="mt-4 text-xs text-fg-subtle">
        Mock Profile 始终可用——不依赖 GPU、Docker 或 API Key
      </div>
    </div>
  );
}
