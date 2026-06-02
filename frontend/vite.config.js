import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      // All /api/* requests → FastAPI backend
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // NOTE: We do NOT proxy /minio or localhost:9000 here.
      // The browser never talks to MinIO directly.
      // PDFs flow: Browser → GET /api/v1/jobs/{id}/pdf → FastAPI → MinIO (server-side)
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.js",
  },
});