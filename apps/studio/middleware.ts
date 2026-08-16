import { NextRequest, NextResponse } from "next/server";

/**
 * API 代理鉴权注入。
 *
 * 背景：浏览器无法为 <img src> / fetch 附带自定义 Authorization；后端配置
 * AVATARLOOM_API_TOKEN 后，control-api（全局 Bearer 校验）与 gateway 管理端点
 * （/api/health/blocks、/api/memory）对无凭证请求一律 401。
 *
 * 本 middleware 在 Next server 侧为 /api/control/*、/api/realtime/* 注入
 * Authorization header，再交给 next.config.mjs 的 rewrites 转发到后端——
 * token 只存在于服务端 env（CONTROL_API_TOKEN / GATEWAY_API_TOKEN），
 * 不会打进客户端 bundle。
 *
 * dev 模式（token 未配置）不加 header，后端 AVATARLOOM_AUTH_DISABLED=1 放行。
 * WS 不经过这里——浏览器 WS 走 gateway auth 消息机制（use-realtime-session）。
 */
const PROXY_TARGETS: ReadonlyArray<{ prefix: string; envName: string }> = [
  { prefix: "/api/control", envName: "CONTROL_API_TOKEN" },
  { prefix: "/api/realtime", envName: "GATEWAY_API_TOKEN" },
];

export function middleware(request: NextRequest) {
  for (const { prefix, envName } of PROXY_TARGETS) {
    if (!request.nextUrl.pathname.startsWith(prefix)) continue;
    const token = process.env[envName];
    if (!token) break; // dev 模式：无 token，透传
    const headers = new Headers(request.headers);
    headers.set("Authorization", `Bearer ${token}`);
    return NextResponse.next({ request: { headers } });
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/api/control/:path*", "/api/realtime/:path*"],
};
