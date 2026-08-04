import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PlaygroundClient } from "./playground-client";

describe("PlaygroundClient", () => {
  it("renders connect button initially", () => {
    render(<PlaygroundClient />);
    expect(screen.getByRole("button", { name: "连接" })).toBeDefined();
  });

  it("shows disconnected state", () => {
    render(<PlaygroundClient />);
    // 状态指示 + disconnected 文字
    expect(screen.getByText("disconnected")).toBeDefined();
  });
});
