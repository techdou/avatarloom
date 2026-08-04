import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 克制专业：白底黑字 + 中性灰
        bg: { DEFAULT: "#ffffff", subtle: "#fafafa" },
        fg: { DEFAULT: "#0a0a0a", muted: "#666666", subtle: "#999999" },
        border: "#e5e5e5",
        accent: { DEFAULT: "#0a0a0a", hover: "#333333" },
        // 状态色（克制）
        ok: "#16a34a",
        warn: "#d97706",
        err: "#dc2626",
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
