import type { NextConfig } from "next";

// Production: static export served by the FastAPI server on the same origin
// (studio/server/main.py), so uploads never pass through a Node proxy.
// Development (`npm run dev`): API calls are proxied to the Python server.
// Note: large uploads should be tested against the production build, since
// the dev proxy buffers request bodies.
const isDev = process.env.NODE_ENV === "development";
const apiTarget = process.env.CLOUD_VIDEO_API ?? "http://127.0.0.1:8000";

const config: NextConfig = {
  output: isDev ? undefined : "export",
  trailingSlash: true,
  images: { unoptimized: true },
  poweredByHeader: false,
  ...(isDev && {
    async rewrites() {
      return [{ source: "/api/:path*", destination: `${apiTarget}/api/:path*` }];
    },
  }),
};

export default config;
