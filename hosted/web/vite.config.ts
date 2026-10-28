import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The page (DAR-634 made it the home page) is built into hosted/public/, which
// FastAPI's static mount serves locally and Vercel's CDN serves in production. The
// whole folder is build output, so emptying it before each build is safe.
export default defineConfig({
  base: "/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: { outDir: "../public", emptyOutDir: true },
  server: {
    // npm run dev talks to the FastAPI app started with uvicorn on :8000.
    proxy: { "/api": "http://localhost:8000" },
  },
});
