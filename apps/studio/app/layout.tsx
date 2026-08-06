import type { Metadata } from "next";
import "./globals.css";
import { QueryProvider } from "@/components/layout/query-provider";
import { ToastProvider } from "@/components/ui/toast";

export const metadata: Metadata = {
  title: "AvatarLoom Studio",
  description: "Composable Digital Human Runtime — Studio",
};

// 在 <html> 解析时同步设好 dark class，避免暗色模式首屏闪烁。
// 这段脚本会被 Next 注入到 <head>，在 React 水合之前执行。
const themeInitScript = `
(function() {
  try {
    var t = localStorage.getItem('theme');
    if (t === 'dark' || (!t && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      document.documentElement.classList.add('dark');
    }
  } catch (e) {}
})();
`;

/**
 * Root layout——只承载全局 providers。
 * AppShell（sidebar + 全屏路由判断）放在 (studio)/layout.tsx 里，
 * 让 /show 等独立演示路由可以脱离 sidebar 渲染。
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>
        <QueryProvider>
          <ToastProvider>{children}</ToastProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
