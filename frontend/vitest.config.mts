import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `.mts` rather than `.ts`: a `.ts` config is loaded as CommonJS here, and Vite warns that the ESM
// syntax in it will stop working under the future default config loader.
//
// The bundled Next.js guide (node_modules/next/dist/docs/01-app/02-guides/testing/vitest.md)
// recommends the `vite-tsconfig-paths` plugin for path aliases, but this Vite version resolves
// tsconfig paths natively and warns that the plugin is redundant. Using the native option.
export default defineConfig({
  plugins: [react()],
  resolve: {
    tsconfigPaths: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules/**", ".next/**"],
  },
});
