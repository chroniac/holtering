import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5178,
    proxy: { "/api": "http://127.0.0.1:8790" },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
