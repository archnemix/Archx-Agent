/*
 * Turn the collected JSON reports into one human-readable summary.
 *
 * Runs in CI after the test jobs finish, writes test-output/SUMMARY.md (and a
 * small latest.json the local tooling reads), then exits non-zero when a suite
 * failed so the workflow turns red.
 */
import { readFile, writeFile, readdir, stat } from 'node:fs/promises';
import path from 'node:path';

const OUT = 'test-output';
const runId = process.argv[2] || 'local';
const runNumber = process.argv[3] || '0';
const sha = process.argv[4] || '';

async function readJson(file) {
  try {
    return JSON.parse(await readFile(file, 'utf8'));
  } catch {
    return null;
  }
}

async function findReports(dir) {
  const found = [];
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return found;
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) found.push(...(await findReports(full)));
    else if (entry.name.endsWith('.json') && entry.name !== 'latest.json') found.push(full);
  }
  return found;
}

const reports = [];
for (const file of await findReports(OUT)) {
  const data = await readJson(file);
  if (data && Array.isArray(data.checks)) reports.push({ file, ...data });
}

const lines = [];
const push = (line = '') => lines.push(line);

push(`# Archx Agent — test run #${runNumber}`);
push();
push(`- run id: \`${runId}\``);
push(`- commit: \`${sha.slice(0, 10)}\``);
push(`- generated: ${new Date().toISOString()}`);
push();

if (!reports.length) {
  push('No machine-readable reports were collected (suites may have crashed before writing).');
} else {
  const total = reports.reduce((sum, r) => sum + r.total, 0);
  const passed = reports.reduce((sum, r) => sum + r.passed, 0);
  const failed = reports.reduce((sum, r) => sum + r.failed, 0);
  push(`**${passed}/${total} checks passed**${failed ? ` — ${failed} failing` : ''}`);
  push();

  push('| suite | checks | passed | failed | duration |');
  push('| --- | ---: | ---: | ---: | ---: |');
  for (const r of reports) {
    push(`| ${r.suite || path.basename(r.file)} | ${r.total} | ${r.passed} | ${r.failed} | ${Math.round((r.durationMs || 0) / 1000)}s |`);
  }
  push();

  for (const r of reports.filter((x) => x.failed > 0)) {
    push(`## Failures — ${r.suite}`);
    push();
    for (const check of r.checks.filter((c) => c.status === 'fail')) {
      push(`- **${check.id}** ${check.name}`);
      push(`  - ${check.message}`);
      if (check.detail) push(`  - detail: \`${JSON.stringify(check.detail).slice(0, 300)}\``);
    }
    push();
  }
}

// screenshot inventory, so a reviewer knows what to look at
const shotsDir = path.join(OUT, 'screenshots');
try {
  const files = (await readdir(shotsDir)).filter((f) => f.endsWith('.png')).sort();
  push('## Screenshots');
  push();
  for (const file of files) {
    const info = await stat(path.join(shotsDir, file));
    push(`- \`test-output/screenshots/${file}\` (${Math.round(info.size / 1024)} KB)`);
  }
} catch {
  push('_No screenshots were produced._');
}

await writeFile(path.join(OUT, 'SUMMARY.md'), lines.join('\n') + '\n');

const summary = reports.map((r) => ({ suite: r.suite, total: r.total, passed: r.passed, failed: r.failed }));
await writeFile(
  path.join(OUT, 'latest.json'),
  JSON.stringify({ runId, runNumber, sha, at: new Date().toISOString(), suites: summary }, null, 2)
);

const failures = reports.reduce((sum, r) => sum + r.failed, 0);
console.log(lines.join('\n'));
process.exit(failures > 0 ? 1 : 0);
