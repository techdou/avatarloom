"use client";

import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { Mic, Square } from "lucide-react";
import { useRealtimeSession } from "@/hooks/use-realtime-session";

/** 连接失败自动重连退避（ms），最多 3 次后转为手动重试。 */
const RETRY_DELAYS = [500, 1000, 2000];

/**
 * 移动端演示客户端——极简全屏体验：
 * - 数字人画面占满（object-cover）
 * - 顶部细连接状态条（绿/红点）
 * - 底部半透明字幕条（最近一条助手回复）
 * - 悬浮大圆形麦克风按钮（底部中央）
 * 无 sidebar / 配置 / 调试。autoConnect=true：进入即连。
 * 连接失败自动指数退避重试 3 次，仍失败转为手动"点按重试"。
 */
export function ShowcaseClient({ profileId, personaId }: { profileId: string; personaId: string }) {
  const session = useRealtimeSession({ profileId, personaId, autoConnect: true });
  const [retryCount, setRetryCount] = useState(0);

  // 连接成功 → 重置重试计数
  useEffect(() => {
    if (session.conn === "connected") setRetryCount(0);
  }, [session.conn]);

  // 连接失败 → 指数退避自动重连（最多 RETRY_DELAYS.length 次）
  useEffect(() => {
    if (session.conn !== "error") return;
    if (retryCount >= RETRY_DELAYS.length) return;
    const t = setTimeout(() => {
      setRetryCount((c) => c + 1);
      void session.connect();
    }, RETRY_DELAYS[retryCount]);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.conn, retryCount]);

  // 取最近一条助手回复作为字幕
  const lastAssistant = [...session.transcript]
    .reverse()
    .find((t) => t.role === "assistant");
  // 正在生成时优先显示 delta
  const caption = session.llmDelta || lastAssistant?.text || "";

  const exhausted = session.conn === "error" && retryCount >= RETRY_DELAYS.length;
  const connDot = {
    connected: "bg-ok",
    connecting: "bg-warn animate-pulse",
    error: "bg-err",
    disconnected: "bg-fg-subtle",
  }[session.conn];

  const connLabel =
    session.conn === "connected"
      ? "已连接"
      : session.conn === "connecting"
        ? "连接中"
        : session.conn === "error"
          ? exhausted
            ? "连接失败"
            : `连接失败，重试 ${retryCount + 1}/${RETRY_DELAYS.length}`
          : "未连接";

  return (
    <div className="relative w-screen h-[100dvh] overflow-hidden bg-black">
      {/* 数字人画面（全屏 cover） */}
      <div className="absolute inset-0 flex items-center justify-center">
        {session.frameUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={session.frameUrl}
            alt="avatar"
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="text-white/60 text-sm">
            {session.conn === "connecting" ? "连接中…" : "等待画面"}
          </div>
        )}
      </div>

      {/* 顶部细连接状态条 */}
      <div className="absolute top-0 inset-x-0 h-8 flex items-center justify-center gap-2 bg-gradient-to-b from-black/50 to-transparent">
        <span className={clsx("w-2 h-2 rounded-full", connDot)} />
        <span className="text-micro text-white/80 font-medium tracking-wide">
          {connLabel}
        </span>
      </div>

      {/* 底部半透明字幕条 */}
      {caption && (
        <div className="absolute bottom-24 inset-x-3 flex justify-center px-2 pointer-events-none">
          <div className="max-w-xl rounded-xl bg-black/55 backdrop-blur-sm px-4 py-2.5 text-white text-sm leading-relaxed text-center shadow-pop">
            {caption}
          </div>
        </div>
      )}

      {/* 错误提示：重试耗尽后变为可点击的手动重试 */}
      {session.error && (
        <div className="absolute top-10 inset-x-3 flex justify-center">
          {exhausted ? (
            <button
              type="button"
              onClick={() => {
                setRetryCount(0);
                void session.connect();
              }}
              className="rounded-md bg-err/90 text-white text-micro px-3 py-1.5 active:scale-95"
            >
              {session.error} —— 点按重试
            </button>
          ) : (
            <div className="rounded-md bg-err/90 text-white text-micro px-3 py-1.5 pointer-events-none">
              {session.error}
            </div>
          )}
        </div>
      )}

      {/* 悬浮大圆形麦克风按钮 */}
      <div className="absolute bottom-6 inset-x-0 flex justify-center">
        <button
          type="button"
          onClick={session.toggleMic}
          disabled={session.conn !== "connected"}
          aria-label={session.micActive ? "停止麦克风" : "开始说话"}
          className={clsx(
            "w-16 h-16 rounded-full flex items-center justify-center border-2 transition-all active:scale-95 disabled:opacity-40",
            session.micActive
              ? "bg-err/90 border-err text-white"
              : "bg-white/90 border-white text-accent hover:bg-white"
          )}
        >
          {session.micActive ? (
            <Square className="w-6 h-6" />
          ) : (
            <Mic className="w-7 h-7" />
          )}
        </button>
      </div>
    </div>
  );
}
