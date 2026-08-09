"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { RefreshCw } from "lucide-react";

interface ServiceStatus {
  ok: boolean | null; // null = 探测中
  detail: string;
}

/**
 * 服务健康卡——实时探活三个服务（经 Next Route Handler 代理）。
 * 30s 轮询 + 手动刷新。状态点：绿=ok / 红=不可达 / 灰=探测中。
 */
export function ServiceHealthCard() {
  const [controlApi, setControlApi] = useState<ServiceStatus>({ ok: null, detail: "" });
  const [gateway, setGateway] = useState<ServiceStatus>({ ok: null, detail: "" });
  const [lastCheck, setLastCheck] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const requestRef = useRef<AbortController | null>(null);

  const probe = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setRefreshing(true);

    const controlProbe = fetch("/api/control/health", { signal: controller.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        const j = await r.json();
        setControlApi({
          ok: true,
          detail: j.db_ok ? "db ok" : "db 异常",
        });
      })
      .catch((e: Error) => {
        if (e.name === "AbortError") return;
        setControlApi({
          ok: false,
          // 网络失败与"可达但响应异常"分开报——后者是契约不符，误导排障
          detail: /fetch failed|Failed to fetch|NetworkError/i.test(e.message)
            ? "不可达"
            : `响应异常（${e.message}）`,
        });
      });
    const gatewayProbe = fetch("/api/realtime/health", { signal: controller.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        const j = await r.json();
        setGateway({ ok: true, detail: "在线" });
      })
      .catch((e: Error) => {
        if (e.name === "AbortError") return;
        setGateway({
          ok: false,
          detail: /fetch failed|Failed to fetch|NetworkError/i.test(e.message)
            ? "不可达"
            : `响应异常（${e.message}）`,
        });
      });

    await Promise.all([controlProbe, gatewayProbe]);
    if (requestRef.current === controller) {
      requestRef.current = null;
      if (!controller.signal.aborted) {
        setRefreshing(false);
        setLastCheck(new Date());
      }
    }
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      await probe();
      if (!stopped) timer = setTimeout(poll, 30000);
    };
    void poll();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      requestRef.current?.abort();
    };
  }, [probe]);

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2>服务健康</h2>
        <button
          type="button"
          onClick={probe}
          disabled={refreshing}
          className="btn btn-sm btn-ghost inline-flex items-center gap-1"
          title="立即探测"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} />
          <span className="hidden sm:inline">刷新</span>
        </button>
      </div>
      <div className="space-y-1 text-sm">
        <ProbeRow label="Control API" port=":8100" status={controlApi} />
        <ProbeRow label="Runtime Gateway" port=":8101" status={gateway} />
        <div className="flex items-center justify-between py-2 border-b border-border last:border-0">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-ok" />
            <span>Studio（本页）</span>
            <span className="text-xs text-fg-subtle font-mono">:3000</span>
          </div>
          <span className="text-xs text-fg-muted">在线</span>
        </div>
      </div>
      {lastCheck && (
        <p className="text-micro text-fg-subtle mt-3">
          上次探测 {lastCheck.toLocaleTimeString()} · 每 30s 自动
        </p>
      )}
    </div>
  );
}

function ProbeRow({
  label,
  port,
  status,
}: {
  label: string;
  port: string;
  status: ServiceStatus;
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border last:border-0">
      <div className="flex items-center gap-2">
        <span
          className={clsx(
            "w-2.5 h-2.5 rounded-full",
            status.ok === null && "bg-fg-subtle animate-pulse",
            status.ok === true && "bg-ok",
            status.ok === false && "bg-err"
          )}
        />
        <span>{label}</span>
        <span className="text-xs text-fg-subtle font-mono">{port}</span>
      </div>
      <span
        className={clsx(
          "text-xs",
          status.ok === false ? "text-err" : "text-fg-muted"
        )}
      >
        {status.ok === null ? "探测中…" : status.detail}
      </span>
    </div>
  );
}
