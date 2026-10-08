import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  // MapLibre alone is about 1 MB and loads only on the map page; the main bundle stays small.
  build: { chunkSizeWarningLimit: 1100 },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // Form tests type every keystroke; leave room for a busy CI machine.
    testTimeout: 15000,
  },
});
