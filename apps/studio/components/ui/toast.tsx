"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";
import { clsx } from "clsx";
import { CheckCircle2, AlertCircle, Info, X } from "lucide-react";

/**
 * 极简 toast——无第三方依赖。
 * 用法：
 *   const toast = useToast();
 *   toast.success("保存成功");
 *   toast.error("上传失败：" + e.message);
 * <ToastProvider /> 已在 RootLayout 里挂载。
 */
type ToastKind = "success" | "error" | "info";
interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastApi {
  success: (msg: string) => void;
  error: (msg: string) => void;
  info: (msg: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // 优雅降级：provider 未挂载时静默无操作，避免抛错打断渲染
    return {
      success: () => {},
      error: () => {},
      info: () => {},
    };
  }
  return ctx;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);

  const remove = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = ++seq.current;
      setItems((prev) => [...prev, { id, kind, message }]);
      // 4 秒后自动消失（error 留久一点）
      const ttl = kind === "error" ? 6000 : 4000;
      window.setTimeout(() => remove(id), ttl);
    },
    [remove]
  );

  const api: ToastApi = {
    success: (m) => push("success", m),
    error: (m) => push("error", m),
    info: (m) => push("info", m),
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastViewport items={items} onClose={remove} />
    </ToastContext.Provider>
  );
}

function ToastViewport({
  items,
  onClose,
}: {
  items: ToastItem[];
  onClose: (id: number) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 w-[min(360px,calc(100vw-2rem))]">
      {items.map((t) => (
        <ToastCard key={t.id} item={t} onClose={() => onClose(t.id)} />
      ))}
    </div>
  );
}

function ToastCard({ item, onClose }: { item: ToastItem; onClose: () => void }) {
  const { icon, tone } = META[item.kind];
  // 进出场动画
  return (
    <div
      role="status"
      className={clsx(
        "flex items-start gap-2.5 rounded-lg border bg-white shadow-pop px-3.5 py-3",
        "animate-[toastIn_.18s_ease-out] dark:bg-bg-subtle dark:shadow-none",
        tone.border,
        tone.bg
      )}
    >
      <span className={clsx("shrink-0 mt-0.5", tone.fg)}>{icon}</span>
      <div className={clsx("flex-1 text-sm leading-snug", tone.fg)}>{item.message}</div>
      <button
        type="button"
        onClick={onClose}
        aria-label="关闭"
        className="shrink-0 text-fg-subtle hover:text-fg transition-colors"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

const META: Record<ToastKind, { icon: React.ReactNode; tone: { fg: string; border: string; bg: string } }> = {
  success: {
    icon: <CheckCircle2 className="w-4 h-4" />,
    tone: {
      fg: "text-ok",
      border: "border-ok/30",
      bg: "bg-ok/5",
    },
  },
  error: {
    icon: <AlertCircle className="w-4 h-4" />,
    tone: {
      fg: "text-err",
      border: "border-err/30",
      bg: "bg-err/5",
    },
  },
  info: {
    icon: <Info className="w-4 h-4" />,
    tone: {
      fg: "text-accent",
      border: "border-accent/30",
      bg: "bg-accent/5",
    },
  },
};

// 纯展示组件到此为止。

