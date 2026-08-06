"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";
import {
  MessageSquare,
  SlidersHorizontal,
  UserCircle2,
  Image as ImageIcon,
  History,
  Settings,
} from "lucide-react";
import { ThemeToggle } from "./theme-toggle";

type NavItem = { href: string; label: string; icon: React.ReactNode };

// 对话优先信息架构：对话为主，配置/记录降级为管理组。
// dashboard/blocks/sessions 不再出现在主导航。
const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "对话",
    items: [
      { href: "/playground", label: "实时对话", icon: <MessageSquare className="w-4 h-4 shrink-0" /> },
    ],
  },
  {
    label: "管理",
    items: [
      { href: "/profiles", label: "运行时配置", icon: <SlidersHorizontal className="w-4 h-4 shrink-0" /> },
      { href: "/personas", label: "人设", icon: <UserCircle2 className="w-4 h-4 shrink-0" /> },
      { href: "/avatars", label: "数字人形象", icon: <ImageIcon className="w-4 h-4 shrink-0" /> },
      { href: "/runs", label: "运行记录", icon: <History className="w-4 h-4 shrink-0" /> },
      { href: "/settings", label: "设置", icon: <Settings className="w-4 h-4 shrink-0" /> },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-60 shrink-0 border-r border-border bg-bg-subtle min-h-screen flex flex-col dark:bg-[#131318] dark:border-border">
      <div className="px-5 py-4 border-b border-border dark:border-border">
        <Link href="/playground" className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-lg bg-accent text-white flex items-center justify-center">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4.5 h-4.5">
              <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" strokeLinejoin="round" />
              <path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v4" strokeLinecap="round" />
            </svg>
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight leading-none">AvatarLoom</div>
            <div className="text-[11px] text-fg-muted mt-1 dark:text-fg-muted">灵构 Studio</div>
          </div>
        </Link>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-5">
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            <div className="section-label px-2 mb-1.5">{group.label}</div>
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const active = pathname?.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={clsx(
                      "flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-sm transition-colors",
                      active
                        ? "bg-accent-soft text-accent font-medium dark:bg-accent/15"
                        : "text-fg-muted hover:text-fg hover:bg-border/40 dark:text-fg-muted dark:hover:text-fg dark:hover:bg-border/30"
                    )}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="px-3 py-3 border-t border-border flex items-center justify-between dark:border-border">
        <div className="text-[11px] text-fg-subtle pl-2">AutoDL RTX 5090 · v0.2.0</div>
        {/* 桌面端主题切换（移动端在顶栏） */}
        <div className="md:flex hidden">
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}
