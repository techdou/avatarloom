import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BlocksHealthCard } from "./blocks-health-card";
import { MemoryManager } from "./memory-manager";
import { ServiceHealthCard } from "./service-health-card";

const apiMocks = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  gatewayFetch: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, ...apiMocks };
});

beforeEach(() => {
  apiMocks.apiFetch.mockReset();
  apiMocks.gatewayFetch.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("management polling", () => {
  it("waits for a block probe to finish before scheduling the next one", async () => {
    vi.useFakeTimers();
    let finishFirst: ((value: unknown) => void) | undefined;
    apiMocks.gatewayFetch
      .mockImplementationOnce(
        () => new Promise((resolve) => {
          finishFirst = resolve;
        })
      )
      .mockResolvedValue({ active: false, profile_id: null, degraded: {}, blocks: [] });

    render(<BlocksHealthCard />);
    expect(apiMocks.gatewayFetch).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(apiMocks.gatewayFetch).toHaveBeenCalledTimes(1);

    await act(async () => {
      finishFirst?.({ active: false, profile_id: null, degraded: {}, blocks: [] });
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(apiMocks.gatewayFetch).toHaveBeenCalledTimes(2);
  });

  it("shows block health request failures", async () => {
    apiMocks.gatewayFetch.mockRejectedValue(new Error("Gateway 401: unauthorized"));

    render(<BlocksHealthCard />);

    expect(await screen.findByText(/Gateway 401: unauthorized/)).toBeDefined();
  });

  it("does not overlap service health polling rounds", async () => {
    vi.useFakeTimers();
    const resolvers: Array<(value: Response) => void> = [];
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise<Response>((resolve) => resolvers.push(resolve))
    );

    render(<ServiceHealthCard />);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      resolvers[0](Response.json({ db_ok: true }));
      resolvers[1](Response.json({ ok: true }));
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});

describe("MemoryManager", () => {
  beforeEach(() => {
    apiMocks.apiFetch.mockResolvedValue([
      {
        id: "mock",
        name: "Mock",
        blocks: { memory: { config: { enabled: true } } },
      },
    ]);
  });

  it("uses the shared default context and lets the persona input be cleared", async () => {
    apiMocks.gatewayFetch.mockResolvedValue({
      active: false,
      persona_id: "demo-assistant",
      items: [],
    });

    render(<MemoryManager />);

    const input = screen.getByLabelText("Persona") as HTMLInputElement;
    expect(input.value).toBe("demo-assistant");
    expect(apiMocks.apiFetch).toHaveBeenCalledWith(
      "/profiles",
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
    fireEvent.change(input, { target: { value: "" } });
    expect(input.value).toBe("");
    fireEvent.blur(input);
    expect(await screen.findByText("Persona ID 不能为空")).toBeDefined();
  });

  it("shows configuration and runtime errors separately", async () => {
    apiMocks.apiFetch.mockRejectedValue(new Error("profiles unavailable"));
    apiMocks.gatewayFetch.mockRejectedValue(new Error("memory unavailable"));

    render(<MemoryManager />);

    await waitFor(() => {
      expect(screen.getByText(/Profile 配置获取失败：profiles unavailable/)).toBeDefined();
      expect(screen.getByText(/memory unavailable/)).toBeDefined();
    });
  });
});
