import { afterEach, describe, expect, it, vi } from "vitest";
import { requestWsTicket } from "./ws-ticket";

afterEach(() => vi.restoreAllMocks());

describe("requestWsTicket", () => {
  it("requests a no-store ticket immediately before connecting", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ ticket: "payload.signature", expires_at: 123 })
    );

    await expect(requestWsTicket()).resolves.toBe("payload.signature");
    expect(fetchMock).toHaveBeenCalledWith("/api/realtime/ticket", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
    });
  });

  it("surfaces ticket endpoint failures instead of opening an unauthenticated socket", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("proxy unavailable", { status: 502 })
    );

    await expect(requestWsTicket()).rejects.toThrow(
      "WS 鉴权凭证获取失败（502）：proxy unavailable"
    );
  });
});
