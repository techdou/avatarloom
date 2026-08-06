import { clsx } from "clsx";

interface MessageBubbleProps {
  role: "user" | "assistant";
  text: string;
  /** 说话人标签。默认 user→"你"、assistant→"助手"；调用方可传 persona label。 */
  label?: string;
  /** true 时追加流式光标（LLM 生成中）。 */
  streaming?: boolean;
}

/**
 * 全站统一聊天气泡——Playground 对话区与 runs/[id] 回放共用。
 * 视觉契约：rounded-lg（8px 标准圆角）、用户泡 accent-soft、助手泡白底边框、
 * 标签 text-micro 中性色。不携带阴影以外的装饰。
 */
export function MessageBubble({ role, text, label, streaming = false }: MessageBubbleProps) {
  const isUser = role === "user";
  const displayLabel = label ?? (isUser ? "你" : "助手");
  return (
    <div className={clsx("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={clsx(
          "max-w-[78%] rounded-lg px-3.5 py-2.5 text-sm leading-relaxed shadow-card",
          isUser
            ? "bg-accent-soft text-fg dark:bg-accent/15 dark:text-fg-dark"
            : "bg-white border border-border dark:bg-bg-subtle-dark dark:border-border dark:text-fg-dark"
        )}
      >
        <div className="text-micro text-fg-subtle mb-1">
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
