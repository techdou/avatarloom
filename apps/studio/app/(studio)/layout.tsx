import { AppShell } from "@/components/layout/app-shell";

/**
 * Studio 路由组的布局——承载 sidebar / 顶栏 / 全屏路由判断。
 * /show 路由不在此组内，因此不会获得 AppShell（独立演示，无 sidebar）。
 */
export default function StudioLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
