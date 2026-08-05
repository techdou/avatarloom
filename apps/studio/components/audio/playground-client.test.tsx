import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PlaygroundClient } from "./playground-client";

/**
 * Playground 视觉层断言——匹配当前 UI（重写自旧版本，旧版断言的文案已不存在）。
 * 只验证未连接初始态的不变量，不验证 WS/音频数据流。
 *
 * 注意：组件依赖浏览器 API（WebSocket、AudioContext、navigator.mediaDevices），
 * jsdom 环境下 connect() 调用会失败，因此只测试初始 disconnected 态。
 */
describe("PlaygroundClient (初始未连接态)", () => {
  it("渲染顶部连接按钮", () => {
    render(<PlaygroundClient />);
    // 顶栏有"连接"按钮；WelcomePane 有"连接并开始"——用精确匹配锁定顶栏那个
    const btn = screen.getByRole("button", { name: /^连接$/ });
    expect(btn).toBeDefined();
  });

  it("未连接时渲染引导态（含连接 CTA 与角色名）", () => {
    render(<PlaygroundClient />);
    // WelcomePane 渲染的醒目 CTA
    expect(screen.getByRole("button", { name: /连接并开始/ })).toBeDefined();
    // 角色名
    expect(screen.getByText("实时数字人 · 小灵")).toBeDefined();
  });

  it("显示未连接状态文案", () => {
    render(<PlaygroundClient />);
    // 顶栏状态行
    expect(screen.getByText("未连接")).toBeDefined();
  });

  it("未连接时麦克风按钮被禁用", () => {
    render(<PlaygroundClient />);
    const micBtn = screen.getByRole("button", { name: /开始说话/ });
    expect(micBtn.hasAttribute("disabled")).toBe(true);
  });
});
