/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 开发时代理 API 到 Control API / Runtime Gateway
  async rewrites() {
    return [
      { source: '/api/control/:path*', destination: 'http://127.0.0.1:8100/api/:path*' },
      { source: '/api/realtime/:path*', destination: 'http://127.0.0.1:8101/api/:path*' },
    ];
  },
};

export default nextConfig;
