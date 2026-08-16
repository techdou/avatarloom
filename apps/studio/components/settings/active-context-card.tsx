"use client";

import { useEffect, useState } from "react";
import { gatewayFetch, type GatewayProfilesResponse, type Persona } from "@/lib/api";

/**
 * 「当前活动」卡——设置页顶部，显示 Playground 实际会用的运行时上下文。
 * 数据源：localStorage（al.profile / al.persona，与 PlaygroundClient 同一套 key）
 * + gateway /profiles（yaml——运行时装配源）与 control-api /personas 拉名称映射。
 * 未连接 API 时降级显示 id。
 */
export function ActiveContextCard() {
  const [profileId, setProfileId] = useState("mock");
  const [personaId, setPersonaId] = useState("demo-assistant");
  const [profileName, setProfileName] = useState<string | null>(null);
  const [personaName, setPersonaName] = useState<string | null>(null);

  useEffect(() => {
    try {
      const p = localStorage.getItem("al.profile");
      const pe = localStorage.getItem("al.persona");
      if (p) setProfileId(p);
      if (pe) setPersonaId(pe);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    let alive = true;
    gatewayFetch<GatewayProfilesResponse>("/profiles")
      .then((data) => {
        if (!alive || !Array.isArray(data?.profiles)) return;
        const hit = data.profiles.find((x) => x.id === profileId);
        if (hit) setProfileName(hit.name);
      })
      .catch(() => {});
    fetch("/api/control/personas")
      .then((r) => (r.ok ? r.json() : []))
      .then((list: Persona[]) => {
        if (!alive || !Array.isArray(list)) return;
        const hit = list.find((x) => x.id === personaId);
        if (hit) setPersonaName(hit.label || hit.name);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [profileId, personaId]);

  return (
    <div className="card">
      <h2 className="mb-4">当前活动</h2>
      <dl className="space-y-1 text-sm">
        <Row k="运行时配置" v={profileName ?? profileId} sub={profileName ? profileId : undefined} />
        <Row k="人设" v={personaName ?? personaId} sub={personaName ? personaId : undefined} />
        <Row k="生效位置" v="实时对话（Playground）与演示页（/show）" />
      </dl>
      <p className="text-xs text-fg-subtle mt-3">
        切换入口在 Playground 顶部上下文条；此处仅展示当前生效值。
      </p>
    </div>
  );
}

function Row({ k, v, sub }: { k: string; v: string; sub?: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border last:border-0">
      <dt className="text-fg-muted">{k}</dt>
      <dd className="text-right">
        <span className="font-medium">{v}</span>
        {sub && <span className="ml-2 text-xs text-fg-subtle font-mono">{sub}</span>}
      </dd>
    </div>
  );
}
