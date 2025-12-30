import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import fs from 'node:fs'
import path from 'node:path'

// https://vitejs.dev/config/
export default defineConfig({
  base: "./",
  plugins: [
    vue(),
    {
      name: 'virtual-events',
      resolveId(id) {
        if (id === 'virtual:events') return id;
      },
      load(id) {
        if (id === 'virtual:events') {
          const rootDir = fileURLToPath(new URL('.', import.meta.url));
          const jsonPath = path.resolve(rootDir, '../resource/umamusume/data/event_data.json');
          try {
            const raw = fs.readFileSync(jsonPath, 'utf-8');
            const data = JSON.parse(raw || '{}');
            const names = Array.isArray(data) ? data : Object.keys(data || {}).sort();

            // Build a map of event -> option count (buttons to render)
            let counts = {};
            if (!Array.isArray(data) && data && typeof data === 'object') {
              for (const [name, value] of Object.entries(data)) {
                let c = 0;
                if (value) {
                  if (Array.isArray(value.choices)) {
                    c = value.choices.length;
                  } else if (value.choices && typeof value.choices === 'object') {
                    c = Object.keys(value.choices).length;
                  }
                  if (!c && value.stats && typeof value.stats === 'object') {
                    c = Object.keys(value.stats).length;
                  }
                }
                counts[name] = c || 0;
              }
            }

            return `export default ${JSON.stringify(names)};\nexport const eventOptionCounts = ${JSON.stringify(counts)};`;
          } catch (e) {
            return 'export default []\nexport const eventOptionCounts = {}';
          }
        }
      }
    }
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  build: {
    outDir: "../public",
    assetsDir: "assets",
    emptyOutDir: true
  }
})
