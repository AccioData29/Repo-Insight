import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

// Informe autocontenido: un solo HTML (JS, CSS y Mermaid incluidos). Uso: npm run build:report
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: { outDir: "dist-report", chunkSizeWarningLimit: 6000, rollupOptions: { output: { inlineDynamicImports: true } } },
});
