import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      // contracts/ is the single source of truth for schemas and example payloads
      '@contracts': path.resolve(__dirname, '../contracts'),
      // exported instances (S9): edge_list.json, display.json (D41) and solution.json once solved
      '@instances': path.resolve(__dirname, '../data/instances'),
    },
  },
  server: {
    fs: {
      allow: [
        __dirname,
        path.resolve(__dirname, '../contracts'),
        path.resolve(__dirname, '../data/instances/even-2025-26'),
      ],
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
  },
});
