import type { NextConfig } from "next";

const backendUrl = (process.env.BACKEND_URL || "http://127.0.0.1:8080").replace(/\/$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  experimental: {
    // PDF parsing and OCR can legitimately take longer than Next.js' 30s
    // rewrite proxy default.
    proxyTimeout: 300_000,
    // Rewrites clone request bodies before proxying. Keep this above the
    // backend's 250 MB upload limit so large document uploads are not truncated.
    middlewareClientMaxBodySize: "260mb",
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
