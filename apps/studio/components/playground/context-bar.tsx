"use client";

import { memo, useCallback } from "react";
import { clsx } from "clsx";
import { Camera, Link2, Power } from "lucide-react";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { useToast } from "@/components/ui/toast";
import type { GatewayProfile, Persona } from "@/lib/api";

type ConnState = "disconnected" | "connecting" | "connected" | "error";

interface ContextBarProps {
  conn: ConnState;
  profileId: string;
  personaId: string;
  /** 下拉选项——由 PlaygroundClient（orchestration 层）统一拉取后传入。 */
  profiles: GatewayProfile[];
  personas: Persona[];
  onProfileChange: (id: string) => void;
  onPersonaChange: (id: string) => void;
  onConnect: () => void;
  onDisconnect: () => void;
  onCaptureFrame?: () => void;
  showDebug: boolean;
  onToggleDebug: (v: boolean) => void;
}

/**
 * Playground 顶部上下文条：连接状态 + profile/persona 选择 + 调试开关 + 主题切换。
 * 纯渲染组件——profiles/personas 选项由调用方拉取传入。
 * 下拉用原生 <select>（不引入 UI 库），样式套 .input。
 *
 * React.memo：高频 setDebugInfo 驱动整树重渲染时，本组件的 props（conn / profileId /
 * 回调引用）大多数时候不变，可跳过重渲染。
 */
export const ContextBar = memo(function ContextBar({
  conn,
  profileId,
  personaId,
  profiles,
  personas,
  onProfileChange,
  onPersonaChange,
  onConnect,
  onDisconnect,
  onCaptureFrame,
  showDebug,
  onToggleDebug,
}: ContextBarProps) {
  const toast = useToast();

  /** 复制 /show 演示页链接（当前 persona + profile）——手机扫码/粘贴即开演示。 */
  const copyShowLink = useCallback(() => {
    const url = `${window.location.origin}/show?persona=${encodeURIComponent(personaId)}&profile=${encodeURIComponent(profileId)}`;
    void copyText(url).then((ok) => {
      if (ok) {
        toast.success("演示链接已复制——发送到手机即可打开演示页");
      } else {
        toast.info(`复制失败，请手动复制：${url}`);
      }
    });
  }, [personaId, profileId, toast]);

  const connDot = {
    connected: "bg-ok",
    connecting: "bg-warn animate-pulse",
    error: "bg-err",
    disconnected: "bg-fg-subtle",
  }[conn];

  const connLabel =
    conn === "connected"
      ? "已连接"
      : conn === "connecting"
        ? "连接中"
        : conn === "error"
          ? "连接失败"
          : "未连接";

  const selectClass =
    "h-8 px-2 py-0 text-xs rounded-md border border-border bg-white shadow-card focus:outline-none focus:ring-2 focus:ring-accent-ring focus:border-accent dark:bg-bg-subtle dark:border-border dark:shadow-none";

  return (
    <div className="card flex flex-wrap items-center gap-x-3 gap-y-2 py-2 px-3">
      {/* 左：连接状态 + 按钮 */}
      <div className="flex items-center gap-2 min-w-0">
        <span className={clsx("w-2.5 h-2.5 rounded-full shrink-0", connDot)} />
        <span className="text-sm font-medium truncate">{connLabel}</span>
      </div>
      {conn === "connected" ? (
        <>
          {onCaptureFrame && (
            <button
              onClick={onCaptureFrame}
              className="btn btn-sm btn-ghost inline-flex items-center gap-1"
              title="截一帧摄像头画面上行分析（或对数字人说「看看我」）"
            >
              <Camera className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">看看我</span>
            </button>
          )}
          <button onClick={onDisconnect} className="btn btn-sm btn-danger">
            断开
          </button>
        </>
      ) : (
        <button
          onClick={onConnect}
          className="btn btn-sm btn-primary inline-flex items-center gap-1"
          disabled={conn === "connecting"}
        >
          <Power className="w-3.5 h-3.5" />
          {conn === "connecting" ? "连接中…" : "连接"}
        </button>
      )}

      <div className="hidden md:block w-px h-5 bg-border dark:bg-border mx-0.5" />

      {/* 中：profile / persona 下拉 */}
      <div className="hidden md:flex items-center gap-2">
        <label className="flex items-center gap-1 text-xs text-fg-muted">
          <span>配置</span>
          <select
            value={profileId}
            onChange={(e) => onProfileChange(e.target.value)}
            className={selectClass}
          >
            {profiles.length === 0 ? (
              <option value={profileId}>{profileId}</option>
            ) : (
              profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))
            )}
          </select>
        </label>
        <label className="flex items-center gap-1 text-xs text-fg-muted">
          <span>人设</span>
          <select
            value={personaId}
            onChange={(e) => onPersonaChange(e.target.value)}
            className={selectClass}
          >
            {personas.length === 0 ? (
              <option value={personaId}>{personaId}</option>
            ) : (
              personas.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label || p.name}
                </option>
              ))
            )}
          </select>
        </label>
      </div>

      {/* 右：演示链接 + 调试 + 主题 */}
      <div className="ml-auto flex items-center gap-3">
        <button
          type="button"
          onClick={copyShowLink}
          className="btn btn-sm btn-ghost inline-flex items-center gap-1"
          title="复制 /show 演示页链接（当前人设 + 配置），手机打开即演示"
        >
          <Link2 className="w-3.5 h-3.5" />
          <span className="hidden md:inline">演示链接</span>
        </button>
        <label className="flex items-center gap-1.5 text-xs text-fg-muted cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showDebug}
            onChange={(e) => onToggleDebug(e.target.checked)}
            className="accent-accent w-3.5 h-3.5"
          />
          <span className="hidden md:inline">调试</span>
        </label>
        <ThemeToggle />
      </div>
    </div>
  );
});

/** 复制文本——clipboard API 优先；非安全上下文（局域网 http 演示场景）降级 execCommand。 */
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
