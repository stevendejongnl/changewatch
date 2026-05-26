import { defineConfig } from "vite";

export default defineConfig({
  build: {
    lib: {
      entry: "src/editor.ts",
      formats: ["iife"],
      name: "CWEditor",
      fileName: () => "editor.js",
    },
    outDir: "../app/static",
    emptyOutDir: false,
    minify: false,
  },
});
