import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PlaygroundClient } from "./playground-client";

describe("PlaygroundClient", () => {
  it("renders connect button initially", () => {
    render(<PlaygroundClient />);
    expect(screen.getByRole("button", { name: "连接" })).toBeDefined();
  });

  it("shows avatar placeholder when no frame", () => {
    render(<PlaygroundClient />);
    expect(screen.getByText("Avatar 显示区")).toBeDefined();
  });

  it("shows disconnected state", () => {
    render(<PlaygroundClient />);
    expect(screen.getByText("disconnected")).toBeDefined();
  });

  it("disables mic button when disconnected", () => {
    render(<PlaygroundClient />);
    const micBtn = screen.getByRole("button", { name: "开启麦克风" });
    expect(micBtn.hasAttribute("disabled")).toBe(true);
  });
});
