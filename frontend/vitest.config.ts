import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Sibling config (not merged into vite.config.ts) so vite.config.ts stays
// typed against plain 'vite' and doesn't need to import vitest's types just
// to run the dev server / production build.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
