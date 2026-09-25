import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the engine runs on :8000 (`uvicorn scp.api.app:app`); Vite proxies /api to it.
// In production the engine serves the built client itself (scp/web/dist).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
