/**
 * Skeleton 占位——纯展示，配合 loading.tsx 自动 Suspense。
 * 用 animate-pulse 模拟加载，无额外依赖。
 */
import { clsx } from "clsx";

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={clsx(
        "rounded-md bg-border/50 animate-pulse dark:bg-border/30",
        className
      )}
    />
  );
}
