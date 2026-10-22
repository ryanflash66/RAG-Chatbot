import path from "node:path";
import { defineConfig } from "vitest/config";

// Kept apart from vite.config.ts so the page's build settings stay as they are.
export default defineConfig({
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  test: { environment: "jsdom" },
});
