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
    { label: "Personas", value: personas.length, href: "/personas", hint: "人设" },
    { label: "Block Definitions", value: blocks.length, href: "/blocks", hint: "模块" },
    { label: "Runtime Profiles", value: profiles.length, href: "/profiles", hint: "运行时配置" },
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">总览</h1>
          <p className="page-desc">AvatarLoom 灵构——模块化实时数字人运行平台 · AutoDL RTX 5090</p>
        </div>
        <Link href="/playground" className="btn btn-primary">进入实时对话</Link>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        {stats.map((s) => (
          <Link key={s.label} href={s.href} className="card card-hover group">
            <div className="flex items-center justify-between">
              <div className="text-sm text-fg-muted">{s.label}</div>
              <span className="badge badge-accent">{s.hint}</span>
            </div>
            <div className="text-3xl font-semibold mt-2 group-hover:text-accent transition-colors">
              {s.value}
            </div>
          </Link>
        ))}
      </div>

      <div className="card">
        <h2 className="mb-4">快速开始</h2>
        <ol className="text-sm space-y-3 text-fg-muted">
          {[
            ["配置人设与形象", "/personas", "创建或查看数字人人设"],
            ["选择运行时配置", "/profiles", "autodl-best：DeepSeek + VoxCPM2 + MuseTalk"],
            ["开始语音对话", "/playground", "连接 Gateway，打开麦克风"],
            ["回看运行记录", "/runs", "每轮对话的录制与指标"],
          ].map(([label, href, desc], i) => (
            <li key={href} className="flex items-start gap-3">
              <span className="w-5 h-5 rounded-full bg-accent-soft text-accent text-[11px] font-semibold flex items-center justify-center shrink-0 mt-0.5">
                {i + 1}
              </span>
              <div>
                <Link href={href} className="font-medium text-fg underline-offset-2 hover:underline">
                  {label}
                </Link>
                <div className="text-xs mt-0.5">{desc}</div>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
