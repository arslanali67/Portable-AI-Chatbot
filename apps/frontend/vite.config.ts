import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],

  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },

  server: {
    port: 3000,

    proxy: {
      "/api": {
        target: "https://portable-ai-chatbot-production.up.railway.app",
        changeOrigin: true,
        secure: true,
      },

      "/widget.js": {
        target: "https://portable-ai-chatbot-production.up.railway.app",
        changeOrigin: true,
        secure: true,
      },
    },
  },

  build: {
    outDir: "dist",
    sourcemap: false,
  },
});