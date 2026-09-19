import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5178,
    proxy: { "/api": "http://127.0.0.1:8790" },
  },
  // Врачи работают с Win7/8.1, где браузеры заморожены на этих версиях
  build: { outDir: "dist", emptyOutDir: true, target: ["chrome109", "firefox115"] },
});
