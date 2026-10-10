import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { defineConfig } from "vitest/config";

const backend = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["brand/ruport-mark.png", "brand/ruport-icon-192.png", "brand/ruport-icon-512.png"],
      manifest: {
        name: "RuPort AI",
        short_name: "RuPort AI",
        description: "Offline-first health records for medical volunteers in rural communities",
        theme_color: "#071b35",
        background_color: "#ffffff",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "brand/ruport-icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "brand/ruport-icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
        ],
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
