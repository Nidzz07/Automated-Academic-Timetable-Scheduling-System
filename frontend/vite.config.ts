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
    },
  },
  server: {
    fs: {
      allow: [__dirname, path.resolve(__dirname, '../contracts')],
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
  },
});
