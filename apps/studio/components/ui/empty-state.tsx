import Link from "next/link";
import { clsx } from "clsx";

interface EmptyStateAction {
  label: string;
  href?: string;
  onClick?: () => void;
}

interface EmptyStateProps {
  /** lucide 图标（不要 emoji）。40×40 中性色方块内居中。 */
  icon?: React.ReactNode;
  /** 一句话，不超 12 字。 */
  title: string;
  description?: string;
  action?: EmptyStateAction;
  /** card = 居中卡片容器（页面级空态）；bare = 轻提示（区块内）。 */
  variant?: "card" | "bare";
}

/**
 * 全站统一空态——替换各页"暂无 X"的散装实现。
 * 视觉硬约束：不画装饰性 SVG、不用 accent 色 icon 底（保持中性）、文案用陈述句。
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  variant = "card",
}: EmptyStateProps) {
  const body = (
    <div className="flex flex-col items-center justify-center text-center py-10 px-6">
      {icon && (
        <div className="w-10 h-10 rounded-lg bg-bg-subtle text-fg-muted flex items-center justify-center mb-3 dark:bg-border/30">
          {icon}
        </div>
      )}
      <div className="text-base font-medium text-fg">{title}</div>
      {description && (
        <p className="text-sm text-fg-muted mt-1 max-w-md">{description}</p>
      )}
      {action && (
        action.href ? (
          <Link href={action.href} className="btn btn-primary mt-4">
            {action.label}
          </Link>
        ) : (
          <button type="button" onClick={action.onClick} className="btn btn-primary mt-4">
            {action.label}
          </button>
        )
      )}
    </div>
  );
  if (variant === "bare") return body;
  return <div className={clsx("card")}>{body}</div>;
}
