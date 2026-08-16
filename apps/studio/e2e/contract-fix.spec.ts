import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

/**
 * 前后端契约修复（2026-08-17）的 UI 实测：
 * profile 下拉数据源（gateway yaml）、Run/Session 上报记录、
 * persona 详情页、settings 健康卡。前置：scripts/dev.py 三服务已起。
 */
const SHOT_DIR = join(process.cwd(), "..", "..", "gui-test-screenshots");
mkdirSync(SHOT_DIR, { recursive: true });

test("T1 Playground：profile 下拉列出 gateway yaml 全部档位", async ({ page }) => {
  await page.goto("/playground");
  // 下拉初始只有 fallback 单项，gateway /profiles 到达后展开为全部档位
  const select = page.getByLabel("配置");
  await expect
    .poll(async () => await select.locator("option").count(), { timeout: 10_000 })
    .toBeGreaterThanOrEqual(9);
  const values = await select.locator("option").evaluateAll((els) =>
    els.map((e) => (e as HTMLOptionElement).value)
  );
  // 关键档位必须可选——修复前这里只有 fallback 一项
  for (const expectId of ["mock", "autodl-best", "local-5070", "full-24gb"]) {
    expect(values, `profile 下拉应含 ${expectId}，实际: ${values}`).toContain(expectId);
  }
  await page.screenshot({ path: join(SHOT_DIR, "t1_playground.png"), fullPage: true });
});

test("T2 Profiles：列表页展示各档位 name 与 blocks 概要", async ({ page }) => {
  await page.goto("/profiles");
  await expect(page.getByText("AutoDL Best (DeepSeek + VoxCPM2 + MuseTalk)")).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByText("Local RTX 5070 Ti", { exact: false })).toBeVisible();
  // blocks badge（数据来自 gateway /api/realtime/profiles）
  await expect(page.getByText(/\d+ blocks/).first()).toBeVisible();
  await page.screenshot({ path: join(SHOT_DIR, "t2_profiles.png"), fullPage: true });
});

test("T3 Runs：显示 gateway 上报的真实 Run 记录", async ({ page }) => {
  await page.goto("/runs");
  // 修复前该页恒空（DB 无生产者）；现在应有 run_ 记录
  await expect(page.locator("a[href^='/runs/run_']").first()).toBeVisible({
    timeout: 10_000,
  });
  await page.screenshot({ path: join(SHOT_DIR, "t3_runs.png"), fullPage: true });
});

test("T4 Run 详情：指标与对话内容来自上报数据", async ({ page }) => {
  await page.goto("/runs");
  const first = page.locator("a[href^='/runs/run_']").first();
  await first.waitFor({ state: "visible", timeout: 10_000 });
  await first.click();
  await expect(page.getByText("延迟指标")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("对话内容")).toBeVisible();
  await page.screenshot({ path: join(SHOT_DIR, "t4_run_detail.png"), fullPage: true });
});

test("T5 Sessions：显示会话记录且状态正确", async ({ page }) => {
  await page.goto("/sessions");
  await expect(page.getByText("ses_", { exact: false }).first()).toBeVisible({
    timeout: 10_000,
  });
  await page.screenshot({ path: join(SHOT_DIR, "t5_sessions.png"), fullPage: true });
});

test("T6 Personas：列表点击进详情页（修复前 404）", async ({ page }) => {
  await page.goto("/personas");
  const card = page.locator("a[href='/personas/verify-helper']");
  await card.waitFor({ state: "visible", timeout: 10_000 });
  await card.click();
  await expect(page).toHaveURL(/\/personas\/verify-helper$/, { timeout: 10_000 });
  await expect(page.getByRole("heading", { name: "系统提示词" })).toBeVisible();
  // SSR 把 prompt 传进了编辑器（textarea 值含 seed 文本）
  const editor = page.locator("textarea").first();
  await expect(editor).toHaveValue(/契约验证助手/, { timeout: 5_000 });
  await page.screenshot({ path: join(SHOT_DIR, "t6_persona_detail.png"), fullPage: true });
});

test("T7 Settings：服务健康与组件健康卡正常探测", async ({ page }) => {
  await page.goto("/settings");
  // 服务健康卡：Control API db ok + Gateway 在线（30s 轮询首拍）
  await expect(page.getByText("db ok")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("在线").first()).toBeVisible();
  // 当前活动卡（gateway profiles 数据源）
  await expect(page.getByText("当前活动")).toBeVisible();
  await page.screenshot({ path: join(SHOT_DIR, "t7_settings.png"), fullPage: true });
});
