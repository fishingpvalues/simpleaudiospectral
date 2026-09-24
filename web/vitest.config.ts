import path from "node:path"
import { defineConfig } from "vitest/config"

// Unit tests cover the pure modules only (lib/ and the viewer's draw code), so
// they run in node without the React and Tailwind plugins.
export default defineConfig({
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  test: { include: ["src/**/*.test.ts"], environment: "node" },
})
