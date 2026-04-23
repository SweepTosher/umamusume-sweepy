import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import fs from 'node:fs'
import path from 'node:path'

// vite config
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
    },
    {
      name: 'restore-races',
      apply: 'build',
      closeBundle() {
        const publicDir = path.join(__dirname, '..', 'public');
        const racesBackupDir = path.join(__dirname, '..', 'backup_races');
        const publicRacesDir = path.join(publicDir, 'races');

        if (fs.existsSync(racesBackupDir)) {
          try {
            fs.rmSync(publicRacesDir, { recursive: true, force: true });
          } catch (e) {
            console.warn(`Failed to remove ${publicRacesDir}: ${e.message}`);
          }
          copyFolderRecursive(racesBackupDir, publicRacesDir);
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

function copyFolderRecursive(src, dest) {
  if (!fs.existsSync(src)) return;
  fs.mkdirSync(dest, { recursive: true });
  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyFolderRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}
