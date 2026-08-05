"use client";

import { useEffect, useState } from "react";
import { Sun, Moon } from "lucide-react";

/**
 * 原生主题切换——不依赖 next-themes。
 * - 初始读 localStorage('theme') 或 prefers-color-scheme
 * - 写 localStorage 并在 <html> 上 toggle 'dark' class
 * - 为避免 SSR 闪烁，layout.tsx 里的 inline script 会先设好 class
 */
export function ThemeToggle({ className }: { className?: string }) {
  const [dark, setDark] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {
      /* ignore quota / privacy mode */
    }
  }

  if (!mounted) {
    // 占位，避免水合不匹配 & icon 闪烁
    return (
      <button
        type="button"
        aria-label="切换主题"
        className={`inline-flex items-center justify-center w-8 h-8 rounded-md border border-border text-fg-muted ${className ?? ""}`}
      >
        <Sun className="w-4 h-4" />
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? "切换到亮色" : "切换到暗色"}
      title={dark ? "切换到亮色" : "切换到暗色"}
      className={`inline-flex items-center justify-center w-8 h-8 rounded-md border border-border text-fg-muted hover:text-fg hover:bg-border/40 transition-colors dark:border-border dark:hover:bg-border/40 ${className ?? ""}`}
    >
      {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
    </button>
  );
}
