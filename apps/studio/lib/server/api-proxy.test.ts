// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest";
import { proxyApiRequest } from "./api-proxy";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("proxyApiRequest", () => {
  it("injects the server token and forwards JSON without trusting client auth", async () => {
    vi.stubEnv("CONTROL_API_BASE", "http://control.internal:8100/api");
    vi.stubEnv("AVATARLOOM_API_TOKEN", "server-secret");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ ok: true }, { status: 201 })
    );
    const request = new Request("http://studio.local/api/control/personas?active=1", {
      method: "POST",
      headers: {
        Authorization: "Bearer attacker-value",
        "Content-Type": "application/json",
        Origin: "http://studio.local",
      },
      body: JSON.stringify({ name: "demo" }),
    });

    const response = await proxyApiRequest(request, "control", ["personas"]);

    expect(response.status).toBe(201);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://control.internal:8100/api/personas?active=1");
    const headers = new Headers(init?.headers);
    expect(headers.get("authorization")).toBe("Bearer server-secret");
    expect(headers.get("origin")).toBeNull();
    expect(await new Response(init?.body).text()).toBe('{"name":"demo"}');
  });

  it("preserves multipart content type and upload bytes", async () => {
    vi.stubEnv("CONTROL_API_BASE", "http://control.internal/api");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ id: "1" }));
    const bytes = new Uint8Array([1, 2, 3, 4]);
    const request = new Request("http://studio.local/api/control/assets", {
      method: "POST",
      headers: { "Content-Type": "multipart/form-data; boundary=test-boundary" },
      body: bytes,
    });

    await proxyApiRequest(request, "control", ["assets"]);

    const init = fetchMock.mock.calls[0][1];
    expect(new Headers(init?.headers).get("content-type")).toBe(
      "multipart/form-data; boundary=test-boundary"
    );
    expect(new Uint8Array(await new Response(init?.body).arrayBuffer())).toEqual(bytes);
  });

  it("streams media responses and preserves Range metadata", async () => {
    vi.stubEnv("CONTROL_API_BASE", "http://control.internal/api");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new Uint8Array([7, 8]), {
        status: 206,
        headers: {
          "Content-Type": "audio/wav",
          "Content-Range": "bytes 0-1/8",
          "Accept-Ranges": "bytes",
        },
      })
    );
    const request = new Request("http://studio.local/api/control/assets/a/file", {
      headers: { Range: "bytes=0-1" },
    });

    const response = await proxyApiRequest(request, "control", ["assets", "a", "file"]);

    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get("range")).toBe("bytes=0-1");
    expect(response.status).toBe(206);
    expect(response.headers.get("content-range")).toBe("bytes 0-1/8");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(new Uint8Array([7, 8]));
  });

  it("rejects cross-site requests before contacting an upstream", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const request = new Request("http://studio.local/api/control/personas", {
      headers: { Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" },
    });

    const response = await proxyApiRequest(request, "control", ["personas"]);

    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("turns upstream connection failures into a 502 response", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("connection refused"));

    const response = await proxyApiRequest(
      new Request("http://studio.local/api/realtime/health"),
      "realtime",
      ["health"]
    );

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({
      detail: "Upstream realtime service is unavailable.",
    });
  });
});
