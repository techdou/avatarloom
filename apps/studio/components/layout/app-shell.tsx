"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";
import { Sidebar } from "./sidebar";
import { ThemeToggle } from "./theme-toggle";

/**
 * 应用外壳——负责响应式 sidebar：
 * - md 以上：固定 240px sidebar（保持原视觉）
 * - md 以下：顶栏汉堡按钮 + 抽屉（drawer）覆盖
 * 抽屉状态由本组件持有；路由变化后自动关闭。
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const pathname = usePathname();

  // 路由变化后关闭抽屉（移动端点完导航项自动收起）
  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  // 抽屉打开时锁背景滚动
  useEffect(() => {
    if (drawerOpen) {
      const prev = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = prev;
      };
    }
  }, [drawerOpen]);

  // ESC 关闭
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  return (
    <div className="flex min-h-screen">
      {/* 桌面固定 sidebar */}
      <div className="hidden md:flex">
        <Sidebar />
      </div>

      {/* 移动端抽屉：overlay + 面板 */}
      {drawerOpen && (
        <div className="md:hidden fixed inset-0 z-50">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-[1px]"
            onClick={() => setDrawerOpen(false)}
            aria-hidden
          />
          <div className="absolute left-0 top-0 bottom-0 w-64 max-w-[80vw] shadow-pop animate-[slideIn_.18s_ease-out]">
            <button
              type="button"
              onClick={() => setDrawerOpen(false)}
              aria-label="关闭菜单"
              className="absolute top-3 right-3 z-10 inline-flex items-center justify-center w-8 h-8 rounded-md border border-border text-fg-muted hover:text-fg hover:bg-border/40 bg-white dark:bg-bg-subtle dark:border-border"
            >
              <X className="w-4 h-4" />
            </button>
            <Sidebar />
          </div>
        </div>
      )}

      <div className="flex-1 min-w-0 flex flex-col">
        {/* 移动端顶栏：仅在 md 以下出现 */}
        <header className="md:hidden sticky top-0 z-30 flex items-center justify-between gap-3 px-4 h-14 border-b border-border bg-white/90 backdrop-blur supports-[backdrop-filter]:bg-white/70 dark:bg-bg-subtle/90 dark:border-border">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            aria-label="打开菜单"
            className="inline-flex items-center justify-center w-9 h-9 rounded-md border border-border text-fg-muted hover:text-fg hover:bg-border/40 transition-colors dark:border-border"
          >
            <Menu className="w-5 h-5" />
          </button>
          <span className="text-sm font-semibold tracking-tight">AvatarLoom</span>
          <ThemeToggle />
        </header>

        <main className="flex-1 overflow-auto">
          <div className="mx-auto max-w-7xl p-4 md:p-6">{children}</div>
        </main>
      </div>
    </div>
  );
}
