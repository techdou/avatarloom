import { clsx } from "clsx";
import { ScanEye } from "lucide-react";

interface MessageBubbleProps {
  role: "user" | "assistant";
  text: string;
  /** 说话人标签。默认 user→"你"、assistant→"助手"；调用方可传 persona label。 */
  label?: string;
  /** true 时追加流式光标（LLM 生成中）。 */
  streaming?: boolean;
  /** tool = 工具结果样式（视觉感知等，info 色系 + 图标，不占 persona 气泡）。 */
  variant?: "default" | "tool";
}

/**
 * 全站统一聊天气泡——Playground 对话区与 runs/[id] 回放共用。
 * 视觉契约：rounded-lg（8px 标准圆角）、用户泡 accent-soft、助手泡白底边框、
 * 标签 text-micro 中性色。不携带阴影以外的装饰。
 * 工具消息（variant="tool"）：info 色系 + ScanEye 图标，与 persona 回复明确区分。
 */
export function MessageBubble({
  role,
  text,
  label,
  streaming = false,
  variant = "default",
}: MessageBubbleProps) {
  const isUser = role === "user";
  const isTool = variant === "tool";
  const displayLabel = label ?? (isUser ? "你" : "助手");
  return (
    <div className={clsx("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={clsx(
          "max-w-[78%] rounded-lg px-3.5 py-2.5 text-sm leading-relaxed shadow-card",
          isTool
            ? "bg-info/5 border border-info/30 text-fg dark:text-fg-dark"
            : isUser
              ? "bg-accent-soft text-fg dark:bg-accent/15 dark:text-fg-dark"
              : "bg-white border border-border dark:bg-bg-subtle-dark dark:border-border dark:text-fg-dark"
        )}
      >
        <div
          className={clsx(
            "text-micro mb-1 flex items-center gap-1",
            isTool ? "text-info" : "text-fg-subtle"
          )}
        >
          {isTool && <ScanEye className="w-3 h-3" />}
          {displayLabel}
          {streaming ? " · 思考中" : ""}
        </div>
        <div className="whitespace-pre-wrap break-words">
          {text}
          {streaming && (
            <span className="inline-block w-1.5 h-3.5 bg-accent ml-0.5 align-middle animate-pulse" />
          )}
        </div>
      </div>
    </div>
  );
}
