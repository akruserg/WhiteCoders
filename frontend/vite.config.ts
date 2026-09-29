import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-сервер проксирует /api на бэкенд (arm_api слушает 5000), CORS не нужен.
// Свой адрес API: VITE_API_TARGET=http://host:port npm run dev
const target = process.env.VITE_API_TARGET ?? "http://127.0.0.1:5000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target, changeOrigin: true },
      "/health": { target, changeOrigin: true },
    },
  },
});
