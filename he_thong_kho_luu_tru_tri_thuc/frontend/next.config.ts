import type { NextConfig } from "next";

if (!process.env.BACKEND_URL) {
  throw new Error("Missing required environment variable: BACKEND_URL");
}

const backendUrl = process.env.BACKEND_URL.replace(/\/$/, "");

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
