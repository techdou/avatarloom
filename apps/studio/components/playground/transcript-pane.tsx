"use client";

import { memo, useEffect, useRef } from "react";
import { clsx } from "clsx";
import { Mic, History } from "lucide-react";
import {
  STATE_META_FALLBACK,
  type ConnState,
  type TranscriptItem,
} from "@/hooks/use-realtime-session";
import { MessageBubble } from "@/components/ui/message-bubble";

interface TranscriptPaneProps {
  transcript: TranscriptItem[];
  llmDelta: string;
  error: string | null;
  conn: ConnState;
  sessionState: string;
  sessionId: string | null;
  /** 助手气泡的说话人标签（persona label / name / id 兜底链）。 */
  assistantLabel: string;
  onOpenRuns: () => void;
}

/**
 * 对话面板——header（状态徽章 + sessionId + 历史入口）+ 气泡列表 + 自动滚动。
 * 外层卡片容器由 PlaygroundClient 提供（内含 TranscriptPane + ControlBar），
 * 本组件根元素只做 flex 布局，不自带 card 样式。
 * 气泡渲染委托给 MessageBubble（与 runs/[id] 回放同一实现）。
 *
 * React.memo：transcript / llmDelta / error / sessionState / sessionId 变化才需重渲染，
 * 高频 debugInfo 刷新（每帧 25/s）不会波及本组件。
 */
export const TranscriptPane = memo(function TranscriptPane({
  transcript,
  llmDelta,
  error,
  conn,
  sessionState,
  sessionId,
  assistantLabel,
  onOpenRuns,
}: TranscriptPaneProps) {
  const chatRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = chatRef.current;
    // jsdom / 某些环境没有 scrollTo——guard 一下避免渲染期抛错
    if (el && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [transcript, llmDelta]);

  const stateMeta = STATE_META_FALLBACK[sessionState] || STATE_META_FALLBACK.idle;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* 对话区 header：桌面端显示，移动端隐藏（空间留给对话） */}
      <div className="hidden md:flex px-4 py-3 border-b border-border items-center justify-between dark:border-border">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">对话</span>
          <span className={clsx("badge", stateMeta.badge)}>{stateMeta.label}</span>
        </div>
        <div className="flex items-center gap-3">
          {sessionId && (
            <div className="text-micro font-mono text-fg-subtle truncate max-w-[200px]">
              {sessionId}
            </div>
          )}
          <button
            type="button"
            onClick={onOpenRuns}
            className="btn btn-sm btn-ghost inline-flex items-center gap-1"
            title="运行记录"
          >
            <History className="w-3.5 h-3.5" />
            历史
          </button>
        </div>
      </div>

      <div ref={chatRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {error && (
          <div className="rounded-lg border border-err/30 bg-err/5 text-err text-xs px-3 py-2">
            {error}
          </div>
        )}
        {transcript.length === 0 && !llmDelta && (
          <div className="h-full flex flex-col items-center justify-center text-center text-fg-subtle px-6">
            <div
              className={clsx(
                "w-14 h-14 rounded-2xl flex items-center justify-center mb-3 transition-colors",
                conn === "connected"
                  ? "bg-accent-soft text-accent dark:bg-accent/15"
                  : "bg-border/40 text-fg-subtle"
              )}
            >
              <Mic className="w-6 h-6" />
            </div>
            <div className="text-sm font-medium text-fg-muted mb-1">
              {conn === "connected" ? "准备就绪" : "等待连接"}
            </div>
            {/* 移动端精简文案；桌面端保留说明 */}
            <div className="hidden md:block text-xs">
              {conn === "connected"
                ? "点击下方麦克风按钮，开始语音对话。讲话时数字人会实时听写并回复。"
                : "先连接 Runtime Gateway，再开启麦克风。"}
            </div>
            <div className="md:hidden text-xs">
              {conn === "connected" ? "点击麦克风开始对话" : "先连接再开启麦克风"}
            </div>
          </div>
        )}
        {transcript.map((item, i) => (
          <MessageBubble
            key={i}
            role={item.role}
            text={item.text}
            label={item.kind === "vision" ? "视觉感知" : item.role === "user" ? "你" : assistantLabel}
            variant={item.kind === "vision" ? "tool" : "default"}
          />
        ))}
        {llmDelta && (
          <MessageBubble role="assistant" text={llmDelta} label={assistantLabel} streaming />
        )}
      </div>
    </div>
  );
});
