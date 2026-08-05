"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";

type NavItem = { href: string; label: string; icon: React.ReactNode };

const icon = (d: string) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    className="w-4 h-4 shrink-0"
  >
    <path d={d} />
  </svg>
);

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "工作台",
    items: [
      {
        href: "/dashboard",
        label: "总览",
        icon: icon("M3 12l9-9 9 9M5 10v10h14V10"),
      },
      {
        href: "/playground",
        label: "实时对话",
        icon: icon("M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"),
      },
    ],
  },
  {
    label: "配置",
    items: [
      {
        href: "/profiles",
        label: "运行时配置",
        icon: icon("M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"),
      },
      {
        href: "/personas",
        label: "人设",
        icon: icon("M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0zM12 14a7 7 0 0 0-7 7h14a7 7 0 0 0-7-7z"),
      },
      {
        href: "/avatars",
        label: "数字人形象",
        icon: icon("M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z"),
      },
      {
        href: "/blocks",
        label: "模块注册表",
        icon: icon("M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"),
      },
    ],
  },
  {
    label: "运行",
    items: [
      {
        href: "/sessions",
        label: "会话",
        icon: icon("M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"),
      },
      {
        href: "/runs",
        label: "运行记录",
        icon: icon("M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M9 13h6M9 17h6"),
      },
      {
        href: "/settings",
        label: "设置",
        icon: icon("M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"),
      },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-60 shrink-0 border-r border-border bg-bg-subtle min-h-screen flex flex-col">
      <div className="px-5 py-4 border-b border-border">
        <Link href="/dashboard" className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-lg bg-accent text-white flex items-center justify-center shadow-accent">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4.5 h-4.5">
              <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" strokeLinejoin="round" />
              <path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v4" strokeLinecap="round" />
            </svg>
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight leading-none">AvatarLoom</div>
            <div className="text-[11px] text-fg-muted mt-1">灵构 Studio</div>
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
                        ? "bg-accent-soft text-accent font-medium"
                        : "text-fg-muted hover:text-fg hover:bg-border/40"
                    )}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                    {active && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-accent" />}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="px-5 py-3 border-t border-border text-[11px] text-fg-subtle">
        AutoDL RTX 5090 · v0.2.0
      </div>
    </aside>
  );
}
