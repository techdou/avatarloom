/** Next Route Handler 使用的内部 API 反向代理。 */

export type ProxyService = "control" | "realtime";

const DEFAULT_BASES: Record<ProxyService, string> = {
  control: "http://127.0.0.1:8100/api",
  realtime: "http://127.0.0.1:8101/api",
};

const BASE_ENV: Record<ProxyService, "CONTROL_API_BASE" | "RUNTIME_GATEWAY_BASE"> = {
  control: "CONTROL_API_BASE",
  realtime: "RUNTIME_GATEWAY_BASE",
};

const HOP_BY_HOP_HEADERS = [
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

const REQUEST_PRIVATE_HEADERS = [
  "authorization",
  "cookie",
  "host",
  "origin",
  "referer",
  "content-length",
];

function isSafeBrowserRequest(request: Request): boolean {
  const site = request.headers.get("sec-fetch-site");
  if (site === "cross-site") return false;

  const origin = request.headers.get("origin");
  return !origin || origin === new URL(request.url).origin;
}

function upstreamUrl(service: ProxyService, path: string[], search: string): URL {
  const base = process.env[BASE_ENV[service]]?.trim() || DEFAULT_BASES[service];
  const normalizedBase = base.endsWith("/") ? base : `${base}/`;
  const encodedPath = path.map((segment) => encodeURIComponent(segment)).join("/");
  const url = new URL(encodedPath, normalizedBase);
  url.search = search;
  return url;
}

function upstreamHeaders(request: Request): Headers {
  const headers = new Headers(request.headers);
  for (const name of [...HOP_BY_HOP_HEADERS, ...REQUEST_PRIVATE_HEADERS]) {
    headers.delete(name);
  }

  const token = process.env.AVATARLOOM_API_TOKEN?.trim();
  if (token) headers.set("authorization", `Bearer ${token}`);
  return headers;
}

function downstreamHeaders(upstream: Response): Headers {
  const headers = new Headers(upstream.headers);
  for (const name of [...HOP_BY_HOP_HEADERS, "set-cookie"]) {
    headers.delete(name);
  }
  return headers;
}

/**
 * 转发 JSON、multipart 和媒体请求，并直接透传响应流（含 Range headers）。
 * 客户端 Authorization 永不转发；内部 token 只从 Next 服务端环境读取。
 */
export async function proxyApiRequest(
  request: Request,
  service: ProxyService,
  path: string[]
): Promise<Response> {
  if (!isSafeBrowserRequest(request)) {
    return Response.json({ detail: "Cross-origin API proxy request rejected." }, { status: 403 });
  }

  const method = request.method.toUpperCase();
  const hasBody = method !== "GET" && method !== "HEAD";

  try {
    const init: RequestInit & { duplex?: "half" } = {
      method,
      headers: upstreamHeaders(request),
      body: hasBody ? request.body : undefined,
      cache: "no-store",
      redirect: "manual",
    };
    // Node/undici 转发 ReadableStream request body 时必须显式声明 duplex。
    // 直接透传避免大文件上传被 Next 全量读入内存。
    if (hasBody && request.body) init.duplex = "half";

    const upstream = await fetch(
      upstreamUrl(service, path, new URL(request.url).search),
      init
    );

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: downstreamHeaders(upstream),
    });
  } catch (error) {
    console.error(`[studio-api-proxy] ${service} upstream request failed`, error);
    return Response.json(
      { detail: `Upstream ${service} service is unavailable.` },
      { status: 502 }
    );
  }
}
