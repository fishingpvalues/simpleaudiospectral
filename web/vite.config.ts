import path from "node:path"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: { proxy: { "/api": process.env.SPECTRALS_API ?? "http://127.0.0.1:4748" } },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1500 },
})
