"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/avatars", label: "Avatars" },
  { href: "/personas", label: "Personas" },
  { href: "/blocks", label: "Block Registry" },
  { href: "/profiles", label: "Runtime Profiles" },
  { href: "/playground", label: "Realtime Playground" },
  { href: "/sessions", label: "Sessions" },
  { href: "/runs", label: "Runs" },
  { href: "/settings", label: "Settings" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-56 shrink-0 border-r border-border bg-bg-subtle min-h-screen">
      <div className="p-4 border-b border-border">
        <Link href="/dashboard" className="block">
          <div className="text-base font-semibold tracking-tight">AvatarLoom</div>
          <div className="text-xs text-fg-muted">灵构 Studio</div>
        </Link>
      </div>
      <nav className="p-2 space-y-0.5">
        {NAV.map((item) => {
          const active = pathname?.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                "block px-3 py-1.5 rounded-md text-sm transition-colors",
                active
                  ? "bg-accent text-white"
                  : "text-fg hover:bg-border/40"
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="absolute bottom-0 w-56 p-3 border-t border-border text-xs text-fg-subtle">
        v0.1.0
      </div>
    </aside>
  );
}
