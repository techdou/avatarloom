import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/layout/sidebar";
import { QueryProvider } from "@/components/layout/query-provider";

export const metadata: Metadata = {
  title: "AvatarLoom Studio",
  description: "Composable Digital Human Runtime — Studio",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <QueryProvider>
          <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 overflow-auto">
              <div className="mx-auto max-w-7xl p-6">{children}</div>
            </main>
          </div>
        </QueryProvider>
      </body>
    </html>
  );
}
