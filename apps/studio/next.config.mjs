/** @type {import('next').NextConfig} */

// 服务端 API 代理目标。默认本地 dev 直连；Docker Compose 里通过环境变量
// 指向容器服务名（http://control-api:27810/api / http://runtime-gateway:27811/api）。
// 与 lib/api.ts 的 CONTROL_API_BASE 约定一致（带 /api 后缀）。
const CONTROL_API = process.env.CONTROL_API_BASE ?? 'http://127.0.0.1:27810/api';
const REALTIME_API = process.env.RUNTIME_GATEWAY_BASE ?? 'http://127.0.0.1:27811/api';

const nextConfig = {
  reactStrictMode: true,
  // 代理 API 到 Control API / Runtime Gateway（浏览器只跟 Studio 同域通信）
  async rewrites() {
    return [
      { source: '/api/control/:path*', destination: `${CONTROL_API}/:path*` },
      { source: '/api/realtime/:path*', destination: `${REALTIME_API}/:path*` },
    ];
  },
};

export default nextConfig;
