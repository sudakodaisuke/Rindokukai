import { cpSync, mkdirSync, copyFileSync } from 'node:fs';
mkdirSync('public', { recursive: true });
copyFileSync('node_modules/pdfjs-dist/build/pdf.worker.min.mjs', 'public/pdf.worker.min.mjs');
for (const dir of ['cmaps', 'standard_fonts', 'wasm']) cpSync(`node_modules/pdfjs-dist/${dir}`, `public/${dir}`, { recursive: true });
