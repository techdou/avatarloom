import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 克制专业：白底黑字 + 中性灰。
        // 暗色值以 *-dark token 形式登记，组件里禁止再写 dark:xx-[#...] 任意值。
        bg: {
          DEFAULT: "#ffffff",
          subtle: "#fafafa",
          dark: "#0a0a0c",
          "subtle-dark": "#131318",
        },
        fg: {
          DEFAULT: "#0a0a0a",
          muted: "#666666",
          subtle: "#999999",
          dark: "#ededf2",
        },
        border: { DEFAULT: "#e5e5e5", strong: "#d4d4d8" },
        accent: {
          DEFAULT: "#4f46e5",
          hover: "#4338ca",
          soft: "#eef2ff",
          ring: "rgba(79, 70, 229, 0.35)",
        },
        // 状态色（克制）——亮暗共用，靠 alpha 叠在底色上自适应
        ok: "#16a34a",
        warn: "#d97706",
        err: "#dc2626",
        info: "#0891b2",
      },
      fontSize: {
        // 元信息/标签/调试数字专用——替代散落的 text-[10px] / text-[11px] 任意值
        micro: ["11px", "14px"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.06)",
        pop: "0 8px 24px rgba(16, 24, 40, 0.10)",
        accent: "0 4px 14px rgba(79, 70, 229, 0.25)",
      },
      transitionDuration: {
        quick: "120ms",
        default: "200ms",
        slow: "400ms",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
