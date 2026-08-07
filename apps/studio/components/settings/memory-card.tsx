"use client";

import { useEffect, useState } from "react";
import { BrainCircuit } from "lucide-react";
import type { RuntimeProfile } from "@/lib/api";

interface MemoryConfig {
  enabled?: boolean;
  apiKeyEnv?: string;
  model?: string;
  embedderModel?: string;
  storeDir?: string;
  topK?: number;
}

/**
 * 「记忆（Memory）」卡——settings 页，显示当前 profile 的 memory block 配置与启用指引。
 * 数据源：/api/control/profiles 中当前选中 profile（localStorage al.profile）的
 * blocks.memory.config。memory 默认 disabled——显示配置状态而非运行时状态
 * （运行时 store 活在 orchestrator 进程，REST 不可达）。
 */
export function MemoryCard() {
  const [profileId, setProfileId] = useState("autodl-best");
  const [cfg, setCfg] = useState<MemoryConfig | null>(null);
  const [found, setFound] = useState<boolean | null>(null);

  useEffect(() => {
    try {
      const p = localStorage.getItem("al.profile");
      if (p) setProfileId(p);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    let alive = true;
    fetch("/api/control/profiles")
      .then((r) => (r.ok ? r.json() : []))
      .then((list: RuntimeProfile[]) => {
        if (!alive || !Array.isArray(list)) return;
        const hit = list.find((x) => x.id === profileId);
        if (!hit) {
          setFound(false);
          return;
        }
        const mem = (hit.blocks as Record<string, { config?: MemoryConfig }>)?.memory;
        if (mem?.config) {
          setCfg(mem.config);
          setFound(true);
        } else {
          setFound(false);
        }
      })
      .catch(() => {
        if (alive) setFound(null);
      });
    return () => {
      alive = false;
    };
  }, [profileId]);

  const enabled = cfg?.enabled === true;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="flex items-center gap-2">
          <BrainCircuit className="w-4 h-4 text-fg-muted" />
          长期记忆（Memory）
        </h2>
        {found !== null && (
          <span className={enabled ? "badge badge-ok" : "badge"}>
            {enabled ? "已启用" : "已关闭"}
          </span>
        )}
      </div>

      {found === false && (
        <p className="text-sm text-fg-muted">
          当前配置 <code className="text-xs">{profileId}</code> 未包含 memory block。
        </p>
      )}

      {cfg && (
        <dl className="space-y-1 text-sm">
          <Row k="抽取模型" v={cfg.model ?? "deepseek-v4-flash"} />
          <Row k="向量模型" v={cfg.embedderModel ?? "BAAI/bge-m3"} />
          <Row k="存储目录" v={cfg.storeDir ?? "data/memory"} mono />
          <Row k="召回条数" v={String(cfg.topK ?? 5)} />
          <Row k="Key 环境变量" v={cfg.apiKeyEnv ?? "DEEPSEEK_API_KEY"} mono />
        </dl>
      )}

      <div className="mt-3 pt-3 border-t border-border text-xs text-fg-subtle space-y-1">
        {enabled ? (
          <p>启用中：session 开始时召回相关记忆注入人设，每轮回复后异步抽取写入。</p>
        ) : (
          <>
            <p>启用步骤（默认关闭，四重降级静默跳过，链路无感）：</p>
            <ol className="list-decimal list-inside space-y-0.5 text-fg-muted">
              <li><code className="text-micro">uv sync --extra memory</code>（mem0ai + qdrant-client）</li>
              <li>下载向量模型 <code className="text-micro">BAAI/bge-m3</code>（约 2GB，走 HF 镜像）</li>
              <li>profile 中 <code className="text-micro">memory.config.enabled: true</code></li>
              <li>配置 <code className="text-micro">DEEPSEEK_API_KEY</code> 环境变量</li>
            </ol>
          </>
        )}
      </div>
    </div>
  );
}

function Row({ k, v, mono = false }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border last:border-0">
      <dt className="text-fg-muted">{k}</dt>
      <dd className={mono ? "font-mono text-xs" : "font-medium text-right"}>{v}</dd>
    </div>
  );
}
