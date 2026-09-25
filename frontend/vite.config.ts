import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { defineConfig } from "vite";

export default defineConfig({
  base: "/cv/",
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "ARIE-CV",
        short_name: "ARIE-CV",
        start_url: "/cv/",
        display: "standalone",
        background_color: "#0f1419",
        theme_color: "#0f1419",
        icons: [
          { src: "/cv/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
        ],
      },
    }),
  ],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "dist" },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
