import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // This app lives inside a monorepo-style folder next to `backend/`. Pinning the
  // root stops Turbopack from walking up and picking a lockfile outside the project.
  turbopack: { root: __dirname },
};

export default nextConfig;
