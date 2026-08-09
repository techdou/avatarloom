"use client";

import { useEffect, useState } from "react";
import { Link2 } from "lucide-react";
import { useToast } from "@/components/ui/toast";
import { computeWsUrl } from "@/hooks/use-realtime-session";
import {
  DEFAULT_PERSONA_ID,
  DEFAULT_PROFILE_ID,
  RUNTIME_CONTEXT_STORAGE,
} from "@/lib/runtime-context";

/**
 * 访问入口卡——当前页面地址、WS 目标、演示链接复制。
 * 隧道场景（页面端口 >10000）显示"隧道模式"徽章——地址一眼可核对。
 */
export function AccessCard() {
  const toast = useToast();
  const [origin, setOrigin] = useState("");
  const [wsUrl, setWsUrl] = useState("");
  const [tunnel, setTunnel] = useState(false);

  useEffect(() => {
    setOrigin(window.location.origin);
    setWsUrl(computeWsUrl());
    setTunnel(parseInt(window.location.port) > 10000);
  }, []);

  const copyShowLink = () => {
    let persona = DEFAULT_PERSONA_ID;
    let profile = DEFAULT_PROFILE_ID;
    try {
      persona = localStorage.getItem(RUNTIME_CONTEXT_STORAGE.persona) || persona;
      profile = localStorage.getItem(RUNTIME_CONTEXT_STORAGE.profile) || profile;
    } catch {
      /* ignore */
    }
    const url = `${origin}/show?persona=${encodeURIComponent(persona)}&profile=${encodeURIComponent(profile)}`;
    void copyText(url).then((ok) => {
      if (ok) toast.success("演示链接已复制——发送到手机即可打开");
      else toast.info(`复制失败，请手动复制：${url}`);
    });
  };

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2>访问入口</h2>
        {tunnel && <span className="badge badge-info">隧道模式</span>}
      </div>
      <dl className="space-y-1 text-sm">
        <Row k="本页地址" v={origin || "…"} mono />
        <Row k="WS 目标" v={wsUrl || "…"} mono />
      </dl>
      <div className="mt-3 pt-3 border-t border-border flex items-center justify-between gap-3">
        <p className="text-xs text-fg-subtle">
          演示页（/show）：无控制台全屏画面，适合手机扫码演示。
        </p>
        <button
          type="button"
          onClick={copyShowLink}
          className="btn btn-sm inline-flex items-center gap-1 shrink-0"
        >
          <Link2 className="w-3.5 h-3.5" />
          复制演示链接
        </button>
      </div>
    </div>
  );
}

function Row({ k, v, mono = false }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 border-b border-border last:border-0">
      <dt className="text-fg-muted shrink-0">{k}</dt>
      <dd className={mono ? "font-mono text-xs truncate" : "font-medium"} title={v}>
        {v}
      </dd>
    </div>
  );
}

/** clipboard API 优先；非安全上下文（局域网 http）降级 execCommand。 */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      return true;
    } catch {
      return false;
    }
  }
}
