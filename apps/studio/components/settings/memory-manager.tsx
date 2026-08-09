"use client";

import { useCallback, useEffect, useState } from "react";
import { BrainCircuit, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import {
  apiFetch,
  gatewayFetch,
  type MemoryListResponse,
  type RuntimeProfile,
} from "@/lib/api";
import { useToast } from "@/components/ui/toast";

interface MemoryConfig {
  enabled?: boolean;
  model?: string;
  embedderModel?: string;
  storeDir?: string;
  topK?: number;
  apiKeyEnv?: string;
}

/**
 * 长期记忆管理卡——Settings 内查看与整理运行时记忆：
 * - 配置状态来自 control-api profile（启用/关闭）
 * - 条目列表来自 gateway /api/memory（按 persona 隔离）
 * - 支持搜索过滤、删除、手动添加；30s 轮询
 */
export function MemoryManager() {
  const toast = useToast();
  const [profileId, setProfileId] = useState("mock");
  const [personaId, setPersonaId] = useState("demo-assistant");
  const [personaDraft, setPersonaDraft] = useState("");
  const [cfg, setCfg] = useState<MemoryConfig | null>(null);
  const [cfgFound, setCfgFound] = useState<boolean | null>(null);
  const [runtime, setRuntime] = useState<MemoryListResponse | null>(null);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastCheck, setLastCheck] = useState<Date | null>(null);

  useEffect(() => {
    try {
      const p = localStorage.getItem("al.profile");
      if (p) setProfileId(p);
      const persona = localStorage.getItem("al.persona");
      if (persona) setPersonaId(persona);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    let alive = true;
    apiFetch<RuntimeProfile[]>("/profiles")
      .then((list) => {
        if (!alive || !Array.isArray(list)) return;
        const hit = list.find((x) => x.id === profileId);
        const mem = hit
          ? (hit.blocks as Record<string, { config?: MemoryConfig }>)?.memory
          : undefined;
        if (mem?.config) {
          setCfg(mem.config);
          setCfgFound(true);
        } else {
          setCfg(null);
          setCfgFound(false);
        }
      })
      .catch(() => {
        if (alive) setCfgFound(null);
      });
    return () => {
      alive = false;
    };
  }, [profileId]);

  const load = useCallback(async (persona: string) => {
    try {
      const data = await gatewayFetch<MemoryListResponse>(
        `/memory?persona_id=${encodeURIComponent(persona)}`
      );
      setRuntime(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLastCheck(new Date());
    }
  }, []);

  useEffect(() => {
    load(personaId);
    const t = setInterval(() => load(personaId), 30000);
    return () => clearInterval(t);
  }, [load, personaId]);

  const enabled = runtime?.active === true && cfg?.enabled !== false;
  const items = (runtime?.items ?? []).filter((m) =>
    query.trim() ? m.text.includes(query.trim()) : true
  );

  const applyPersona = () => {
    const v = personaDraft.trim();
    if (!v) return;
    setPersonaId(v);
    try {
      localStorage.setItem("al.persona", v);
    } catch {
      /* ignore */
    }
  };

  const removeItem = async (m: { id: string | null }) => {
    if (!m.id) return;
    setBusy(true);
    try {
      const res = await gatewayFetch<{ ok: boolean; error?: string | null }>(
        `/memory/${encodeURIComponent(m.id)}`,
        { method: "DELETE" }
      );
      if (res.ok) {
        toast.success("记忆已删除");
        await load(personaId);
      } else {
        toast.error(res.error ?? "删除失败");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const addItem = async () => {
    const text = draft.trim();
    if (!text) return;
    setBusy(true);
    try {
      const res = await gatewayFetch<{ ok: boolean; error?: string | null }>(
        "/memory",
        {
          method: "POST",
          body: JSON.stringify({ text, persona_id: personaId }),
        }
      );
      if (res.ok) {
        setDraft("");
        toast.success("已写入一条记忆");
        await load(personaId);
      } else {
        toast.error(res.error ?? "写入失败");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="flex items-center gap-2">
          <BrainCircuit className="w-4 h-4 text-fg-muted" />
          长期记忆（Memory）
        </h2>
        <div className="flex items-center gap-2">
          {cfgFound === false && <span className="badge">未配置</span>}
          {cfgFound === true && (
            <span className={enabled ? "badge badge-ok" : "badge"}>
              {enabled ? "运行中" : "已关闭"}
            </span>
          )}
          <button
            type="button"
            onClick={() => load(personaId)}
            className="btn btn-sm btn-ghost inline-flex items-center gap-1"
            title="立即刷新"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">刷新</span>
          </button>
        </div>
      </div>

      {cfgFound === false && (
        <p className="text-sm text-fg-muted mb-3">
          当前 profile <code className="text-xs">{profileId}</code> 未包含 memory block。
        </p>
      )}

      {cfg && (
        <dl className="space-y-1 text-sm mb-3">
          <Row k="抽取模型" v={cfg.model ?? "deepseek-v4-flash"} />
          <Row k="向量模型" v={cfg.embedderModel ?? "BAAI/bge-m3"} />
          <Row k="存储目录" v={cfg.storeDir ?? "data/memory"} mono />
        </dl>
      )}

      {/* persona 选择 + 搜索 */}
      <div className="flex flex-col sm:flex-row gap-2 mb-3">
        <div className="flex items-center gap-2 flex-1">
          <label className="text-xs text-fg-subtle shrink-0" htmlFor="mem-persona">
            Persona
          </label>
          <input
            id="mem-persona"
            className="input font-mono flex-1 min-w-0"
            value={personaDraft || personaId}
            onChange={(e) => setPersonaDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") applyPersona();
            }}
            onBlur={applyPersona}
            placeholder="persona id"
          />
        </div>
        <div className="relative flex-1">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-subtle" />
          <input
            className="input pl-8 w-full"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索记忆…"
          />
        </div>
      </div>

      {error && (
        <p className="text-sm text-err mb-3">获取失败：{error}（确认 Gateway 已启动）</p>
      )}

      {!runtime && !error && (
        <p className="text-sm text-fg-muted animate-pulse">探测中…</p>
      )}

      {runtime && !runtime.active && (
        <div className="text-sm text-fg-muted space-y-2">
          <p>memory block 未启用或当前无活跃会话。</p>
          <p className="text-xs text-fg-subtle">
            启用步骤：<code className="text-micro">uv sync --extra memory</code> →
            下载向量模型 <code className="text-micro">BAAI/bge-m3</code> →
            profile 中 <code className="text-micro">memory.config.enabled: true</code> →
            配置 <code className="text-micro">DEEPSEEK_API_KEY</code>。
          </p>
        </div>
      )}

      {runtime?.active && (
        <>
          {items.length === 0 ? (
            <p className="text-sm text-fg-muted py-3">
              {query ? "没有匹配的记忆。" : "还没有记忆条目，对话几轮后会自动抽取。"}
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {items.map((m) => (
                <li key={m.id ?? m.text} className="group flex items-start gap-2 py-2">
                  <p className="flex-1 text-sm leading-snug break-words">{m.text}</p>
                  <button
                    type="button"
                    onClick={() => removeItem(m)}
                    disabled={busy || !m.id}
                    className="opacity-0 group-hover:opacity-100 focus:opacity-100 text-fg-subtle hover:text-err transition-opacity shrink-0 mt-0.5 disabled:opacity-0"
                    title="删除这条记忆"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="flex items-center gap-2 mt-3 pt-3 border-t border-border">
            <input
              className="input flex-1"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") addItem();
              }}
              placeholder="手动添加一条记忆…"
            />
            <button
              type="button"
              onClick={addItem}
              disabled={busy || !draft.trim()}
              className="btn btn-sm inline-flex items-center gap-1"
            >
              <Plus className="w-3.5 h-3.5" />
              添加
            </button>
          </div>
        </>
      )}

      {lastCheck && (
        <p className="text-micro text-fg-subtle mt-3">
          {runtime?.active ? `${items.length} 条（共 ${runtime.items.length}）· ` : ""}
          上次刷新 {lastCheck.toLocaleTimeString()} · 每 30s 自动
        </p>
      )}
    </div>
  );
}

function Row({ k, v, mono = false }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between py-1 border-b border-border last:border-0">
      <dt className="text-fg-muted text-xs">{k}</dt>
      <dd className={mono ? "font-mono text-xs" : "font-medium text-right text-xs"}>
        {v}
      </dd>
    </div>
  );
}
