import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The page is served at /new/ beside the current one (hosted/public/index.html) until
// DAR-634 swaps them; it is built into hosted/public/new/, which FastAPI's static mount
// serves locally and Vercel's CDN serves in production.
export default defineConfig({
  base: "/new/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: { outDir: "../public/new", emptyOutDir: true },
  server: {
    // npm run dev talks to the FastAPI app started with uvicorn on :8000.
    proxy: { "/api": "http://localhost:8000" },
  },
});
