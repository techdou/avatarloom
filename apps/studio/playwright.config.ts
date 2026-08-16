import { defineConfig } from "@playwright/test";

/**
 * Studio e2e——连系统 Chrome（channel，零浏览器二进制下载），
 * 前置条件：scripts/dev.py 三服务已起（8100/8101/3000）。
 * make e2e / pnpm --filter @avatarloom/studio exec playwright test
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:3000",
    channel: "chrome",
    headless: true,
  },
  outputDir: "./e2e-results",
});
