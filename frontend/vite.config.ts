/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vite";

const backend = process.env.VITE_BACKEND ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    port: 5173,
    // One origin in dev: the browser talks to Vite, Vite forwards to FastAPI (REST and WebSocket)
    proxy: { "/api": backend, "/ws": { target: backend, ws: true } },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["tests/setup.ts"],
    globalSetup: ["tests/globalSetup.ts"],
    testTimeout: 20000,
    hookTimeout: 60000,
    fileParallelism: false,
  },
});
