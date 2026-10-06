import { execFileSync } from 'node:child_process';
import { copyFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const compiler = createRequire(import.meta.url).resolve('typescript/bin/tsc');
const project = fileURLToPath(new URL('../tsconfig.json', import.meta.url));
execFileSync(process.execPath, [compiler, '-p', project], { stdio: 'inherit' });
const skillScripts = new URL('../../../skills/tervik/scripts/', import.meta.url);
mkdirSync(skillScripts, { recursive: true });
copyFileSync(new URL('../dist/index.js', import.meta.url), new URL('tervik-client.mjs', skillScripts));
copyFileSync(new URL('../dist/index.d.ts', import.meta.url), new URL('tervik-client.d.mts', skillScripts));
