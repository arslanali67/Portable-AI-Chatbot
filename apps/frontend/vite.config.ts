import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],

  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // Node's built-in global `localStorage` (on by default since Node 26,
    // non-functional without --localstorage-file) shadows jsdom's
    // window.localStorage in worker processes; disable it so jsdom's wins.
    execArgv: ["--no-experimental-webstorage"],
    // Default pattern (src/**) made explicit, plus packages/widget's own
    // test file — that package has no build step/tooling of its own, so
    // its tests reuse this already-installed Vitest+jsdom setup rather
    // than standing up a second toolchain for one file.
    include: [
      "src/**/*.{test,spec}.{ts,tsx}",
      "../../packages/widget/**/*.{test,spec}.js",
    ],
  },

  server: {
    port: 3000,

    fs: {
      // Allow serving packages/widget/widget.test.js (a sibling of this
      // app, outside the default project-root fs boundary) so Vitest can
      // load it — see test.include below.
      allow: ["../.."],
    },

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