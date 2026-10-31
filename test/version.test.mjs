import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
const json=p=>JSON.parse(readFileSync(new URL('../'+p,import.meta.url),'utf8'));
test('npm, lockfile and desktop product metadata all identify 1.0.0',()=>{
  assert.equal(json('package.json').version,'1.0.0');assert.equal(json('package-lock.json').version,'1.0.0');
  assert.equal(json('package-lock.json').packages[''].version,'1.0.0');assert.equal(json('src-tauri/tauri.conf.json').version,'1.0.0');
  assert.match(readFileSync(new URL('../src-tauri/Cargo.toml',import.meta.url),'utf8'),/\[package\][\s\S]*?version = "1\.0\.0"/);
});
test('rejected Python implementation and its old model matrix are absent',()=>{
  for(const p of ['pyproject.toml','src/archx_agent','.github/workflows/model-matrix.yml'])assert.equal(existsSync(new URL('../'+p,import.meta.url)),false,p);
});
