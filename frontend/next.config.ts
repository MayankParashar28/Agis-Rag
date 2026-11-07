import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Required by frontend/Dockerfile, which copies .next/standalone
  output: "standalone",
  transpilePackages: ["@neondatabase/auth", "better-auth"],
};

export default nextConfig;
