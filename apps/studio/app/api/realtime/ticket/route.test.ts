// @vitest-environment node

import { createHmac } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

describe("POST /api/realtime/ticket", () => {
  it("returns a short-lived, verifiable HMAC ticket", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-10T00:00:00Z"));
    vi.stubEnv("AVATARLOOM_API_TOKEN", "ticket-secret");

    const response = await POST(
      new Request("http://studio.local/api/realtime/ticket", { method: "POST" })
    );
    const result = (await response.json()) as { ticket: string; expires_at: number };
    const [payloadPart, signaturePart] = result.ticket.split(".");
    const payload = JSON.parse(Buffer.from(payloadPart, "base64url").toString("utf8"));

    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(result.expires_at).toBe(1786320060);
    expect(payload).toMatchObject({ aud: "avatarloom-ws", exp: 1786320060 });
    expect(payload.nonce).toMatch(/^[A-Za-z0-9_-]{22}$/);
    expect(signaturePart).toBe(
      createHmac("sha256", "ticket-secret").update(payloadPart, "ascii").digest("base64url")
    );
  });

  it("does not mint a ticket when auth is explicitly unconfigured", async () => {
    vi.stubEnv("AVATARLOOM_API_TOKEN", "");
    vi.stubEnv("AVATARLOOM_AUTH_DISABLED", "1");

    const response = await POST(
      new Request("http://studio.local/api/realtime/ticket", { method: "POST" })
    );

    expect(await response.json()).toEqual({ ticket: null, expires_at: null });
  });

  it("fails closed when neither a token nor explicit dev mode is configured", async () => {
    vi.stubEnv("AVATARLOOM_API_TOKEN", "");
    vi.stubEnv("AVATARLOOM_AUTH_DISABLED", "0");
    const response = await POST(
      new Request("http://studio.local/api/realtime/ticket", { method: "POST" })
    );
    expect(response.status).toBe(503);
  });

  it("rejects a cross-origin mint request", async () => {
    vi.stubEnv("AVATARLOOM_API_TOKEN", "ticket-secret");

    const response = await POST(
      new Request("http://studio.local/api/realtime/ticket", {
        method: "POST",
        headers: { Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" },
      })
    );

    expect(response.status).toBe(403);
  });
});
