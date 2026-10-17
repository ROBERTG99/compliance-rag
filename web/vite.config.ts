/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const apiTarget = process.env.CRAG_API_URL ?? "http://localhost:8610";
const oidcTarget = process.env.CRAG_OIDC_URL ?? "http://localhost:8612";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 8600,
    proxy: {
      "/v1": apiTarget,
      "/healthz": apiTarget,
      "/readyz": apiTarget,
      "/oidc": { target: oidcTarget, rewrite: (path) => path.replace(/^\/oidc/, "") },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/main.tsx", "src/api/schema.d.ts"],
      thresholds: { lines: 70 },
      reporter: ["text-summary", "json-summary"],
    },
  },
});
