import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  transpilePackages: ["@neondatabase/auth", "better-auth"],
};

export default nextConfig;
