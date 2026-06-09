import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { execSync } from 'node:child_process'

function getVersion(): string {
  try {
    return execSync('git describe --tags --abbrev=0', { encoding: 'utf-8' }).trim()
  } catch {
    return 'dev'
  }
}

// In Docker dev, backend is reachable by service name; locally it's localhost.
const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000'
const wsTarget  = process.env.VITE_WS_TARGET  ?? 'ws://localhost:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    host: true,
    allowedHosts: 'all',
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/ws':  { target: wsTarget, ws: true },
    },
  },
  define: {
    __APP_VERSION__: JSON.stringify(getVersion()),
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
