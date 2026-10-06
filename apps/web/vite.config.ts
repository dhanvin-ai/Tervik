import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': process.env.TERVIK_API_URL || 'http://127.0.0.1:8000',
      '/v1': process.env.TERVIK_API_URL || 'http://127.0.0.1:8000',
    },
  },
});
