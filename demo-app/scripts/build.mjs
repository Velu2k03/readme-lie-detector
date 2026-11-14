import { cp, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const src = fileURLToPath(new URL('../src/', import.meta.url));
const dist = fileURLToPath(new URL('../dist/', import.meta.url));
await rm(dist, { recursive: true, force: true });
await cp(src, dist, { recursive: true });
console.log('built dist/');
