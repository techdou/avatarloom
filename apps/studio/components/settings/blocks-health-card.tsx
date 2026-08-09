"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { Blocks, RefreshCw } from "lucide-react";
import { gatewayFetch, type BlockHealthReport } from "@/lib/api";

const STATUS_META: Record<
  string,
  { dot: string; label: string; text: string; ring?: string }
> = {
  healthy: { dot: "bg-ok", label: "正常", text: "text-fg-muted" },
  not_ready: { dot: "bg-warn", label: "未就绪", text: "text-warn" },
  degraded: { dot: "bg-warn", label: "已降级", text: "text-warn" },
  unhealthy: { dot: "bg-err", label: "异常", text: "text-err" },
  absent: { dot: "bg-fg-subtle", label: "未装配", text: "text-fg-subtle" },
};

/**
 * 组件（Block）健康卡——积木式装配的可视化：
 * 每个 category 一行，状态来自 gateway /api/health/blocks
 * （调 Block.health() + 装配期降级链），30s 轮询。
 */
export function BlocksHealthCard() {
  const [report, setReport] = useState<BlockHealthReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [lastCheck, setLastCheck] = useState<Date | null>(null);
  const requestRef = useRef<AbortController | null>(null);

  const probe = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setRefreshing(true);
    try {
      const data = await gatewayFetch<BlockHealthReport>("/health/blocks", {
        signal: controller.signal,
      });
      setReport(data);
      setError(null);
    } catch (e: unknown) {
      if (e instanceof Error && e.name === "AbortError") return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        if (!controller.signal.aborted) {
          setRefreshing(false);
          setLastCheck(new Date());
        }
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

  const degradedCount =
    report?.blocks.filter((b) => b.status === "degraded" || b.status === "unhealthy")
      .length ?? 0;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="flex items-center gap-2">
          <Blocks className="w-4 h-4 text-fg-muted" />
          组件健康
        </h2>
        <div className="flex items-center gap-2">
          {report?.active && degradedCount > 0 && (
            <span className="badge badge-warn">{degradedCount} 个异常</span>
          )}
          {report?.active && degradedCount === 0 && (
            <span className="badge badge-ok">全部正常</span>
          )}
          <button
            type="button"
            onClick={probe}
            disabled={refreshing}
            className="btn btn-sm btn-ghost inline-flex items-center gap-1"
            title="立即刷新"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} />
            <span className="hidden sm:inline">刷新</span>
          </button>
        </div>
      </div>

      {error && (
        <p className="text-sm text-err mb-3">
          获取失败：{error}（确认 Gateway 已启动）
        </p>
      )}

      {!report ? (
        !error && (
          <p className="text-sm text-fg-muted animate-pulse">探测中…</p>
        )
      ) : !report.active ? (
        <div className="text-sm text-fg-muted space-y-2">
          <p>当前没有活跃会话，组件尚未装配。</p>
          <p className="text-xs text-fg-subtle">
            打开 Playground 发起一次对话后，这里会列出每个积木的实时状态。
          </p>
        </div>
      ) : (
        <div className="space-y-1">
          {report.blocks.map((b) => {
            const meta = STATUS_META[b.status] ?? STATUS_META.absent;
            const degradedTo = report.degraded[b.category];
            return (
              <div
                key={b.category}
                className={clsx(
                  "flex items-center justify-between gap-3 py-2 border-b border-border last:border-0",
                  (b.status === "unhealthy" || b.status === "degraded") &&
                    "border-l-2 border-l-warn pl-2",
                  b.status === "unhealthy" && "border-l-err"
                )}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className={clsx(
                      "w-2.5 h-2.5 rounded-full shrink-0",
                      meta.dot
                    )}
                  />
                  <span className="text-xs font-medium text-fg-subtle w-14 shrink-0">
                    {b.category}
                  </span>
                  <span className="font-mono text-xs truncate">
                    {b.block_id ?? "—"}
                  </span>
                  {b.deployment && (
                    <span className="badge hidden md:inline-flex">{b.deployment}</span>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0 min-w-0">
                  {b.latency_ms != null && (
                    <span className="text-xs text-fg-subtle font-mono">
                      {b.latency_ms}ms
                    </span>
                  )}
                  {degradedTo && (
                    <span className="text-xs text-warn" title="装配期降级">
                      降级自 {degradedTo}
                    </span>
                  )}
                  <span className={clsx("text-xs", meta.text)}>{meta.label}</span>
                </div>
              </div>
            );
          })}
          <p className="text-micro text-fg-subtle pt-1">
            profile={report.profile_id ?? "—"} · 降级表
            {Object.keys(report.degraded).length
              ? ` ${Object.entries(report.degraded)
                  .map(([k, v]) => `${k}→${v}`)
                  .join("、")}`
              : " 无"}
          </p>
        </div>
      )}

      {lastCheck && (
        <p className="text-micro text-fg-subtle mt-3">
          上次刷新 {lastCheck.toLocaleTimeString()} · 每 30s 自动
        </p>
      )}
    </div>
  );
}
