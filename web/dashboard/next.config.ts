import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The browser talks to the API directly (CORS) with an in-memory access token; the refresh
  // token stays in an httpOnly cookie handled by the /session route handlers.
  poweredByHeader: false,
  output: "standalone", // a self-contained server for the Docker image
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=(self)" },
        ],
      },
    ];
  },
};

export default nextConfig;
