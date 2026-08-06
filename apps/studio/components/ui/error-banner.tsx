interface ErrorBannerProps {
  error: string;
  /** 排查提示，如"请确认 control-api 已启动（默认端口 8100）"。 */
  hint?: string;
  onRetry?: () => void;
}

/**
 * 全站统一错误条——替换各页散装的 err 卡片。
 * 视觉契约：rounded-lg border-err/30 bg-err/5，错误文案 + 可选排查提示 + 可选重试。
 */
export function ErrorBanner({ error, hint, onRetry }: ErrorBannerProps) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-err/30 bg-err/5 px-4 py-3 text-sm text-err flex items-start justify-between gap-3"
    >
      <div className="min-w-0">
        <div className="font-medium">加载失败</div>
        <div className="text-xs mt-0.5 break-words">{error}</div>
        {hint && <div className="text-xs mt-1 text-err/80">{hint}</div>}
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="btn btn-sm shrink-0 border-err/30 text-err hover:bg-err/5"
        >
          重试
        </button>
      )}
    </div>
  );
}
