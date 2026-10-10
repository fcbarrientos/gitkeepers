import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { defineConfig } from "vitest/config";

const backend = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icon.svg"],
      manifest: {
        name: "GitKeepers",
        short_name: "GitKeepers",
        description: "Offline health records for barangay health workers",
        theme_color: "#1d3fbf",
        background_color: "#ffffff",
        display: "standalone",
        start_url: "/",
        icons: [{ src: "icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" }],
      },
      workbox: {
        // App shell only: API responses always come from the local backend.
        navigateFallbackDenylist: [/^\/api/, /^\/docs/, /^\/redoc/, /^\/openapi\.json/, /^\/health/],
        runtimeCaching: [],
      },
    }),
  ],
  server: { proxy: { "/api": backend, "/health": backend } },
  // Generous timeout: these run on modest laptops, often while the local model is busy.
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"], testTimeout: 20000 },
});
