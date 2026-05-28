import { defineConfig } from "vite";

const entry = process.env.VITE_ENTRY ?? "editor";

const entries: Record<string, { entry: string; name: string }> = {
  editor: { entry: "src/editor.ts", name: "CWEditor" },
  chart: { entry: "src/chart.ts", name: "CWChart" },
};

const { entry: entryFile, name } = entries[entry];

export default defineConfig({
  build: {
    lib: {
      entry: entryFile,
      formats: ["iife"],
      name,
      fileName: () => `${entry}.js`,
    },
    outDir: "../app/static",
    emptyOutDir: false,
    minify: false,
  },
});
