import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = path.join(root, 'apps/api/.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
if (!existsSync(python)) {
  console.error('Run npm run setup:api before starting Tervik.');
  process.exit(1);
}
if (existsSync(path.join(root, '.env'))) process.loadEnvFile(path.join(root, '.env'));
const children = [];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) child.kill('SIGTERM');
  setTimeout(() => {
    for (const child of children) if (child.exitCode === null) child.kill('SIGKILL');
    process.exit(code);
  }, 2000).unref();
  process.exitCode = code;
}
function run(command, args) {
  const child = spawn(command, args, { cwd: root, env: process.env, stdio: 'inherit' });
  children.push(child);
  child.on('error', error => { console.error(error.message); stop(1); });
  child.on('exit', code => { if (!stopping) stop(code ?? 1); });
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
run(python, ['-m', 'uvicorn', 'app.main:app', '--app-dir', 'apps/api', '--host', '127.0.0.1', '--port', '8000', '--reload', '--reload-dir', 'apps/api/app']);
if (!process.argv.includes('--api-only')) {
  run(process.platform === 'win32' ? 'npm.cmd' : 'npm', ['run', 'dev', '--workspace', '@tervik/web', '--', '--host', '127.0.0.1', '--port', '5173', '--strictPort']);
}
