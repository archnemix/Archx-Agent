#!/usr/bin/env node
/*
 * Ask CI to run the browser suites and wait for the results to land in the
 * working tree.
 *
 *   node tests/ci/run-remote.mjs            # visual + interaction + api
 *   node tests/ci/run-remote.mjs --api      # API job only, still through CI
 *
 * The sentinel file is the trigger: touching it produces a tiny commit, which
 * is what the workflow listens for. Results come back as a normal commit from
 * the bot, so `git pull --rebase` is all the local side needs.
 */
import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { setTimeout as sleep } from 'node:timers/promises';

const sentinel = 'tests/ci/run-browser-tests';
const args = process.argv.slice(2);
const label = args.filter((a) => a.startsWith('--')).join(' ') || 'all suites';

const git = (...a) => execFileSync('git', a, { encoding: 'utf8' }).trim();
const gh = (...a) => execFileSync('gh', a, { encoding: 'utf8' }).trim();

const branch = git('rev-parse', '--abbrev-ref', 'HEAD');
if (!branch.startsWith('arena/')) {
  console.log(`refusing to trigger from "${branch}" — CI publishes back to the pushed branch`);
  process.exit(1);
}

writeFileSync(sentinel, `${new Date().toISOString()} ${label}\n`);
git('add', sentinel);
git('-c', 'user.name=arena-agent', '-c', 'user.email=agent@arena.ai', 'commit', '-q', '-m', `test: request CI run (${label})`);
git('push', '-q', 'origin', branch);
console.log(`pushed trigger to ${branch}; waiting for the run to appear…`);

let runId = null;
for (let attempt = 0; attempt < 30 && !runId; attempt += 1) {
  await sleep(4000);
  const list = gh('run', 'list', '--branch', branch, '--workflow', 'browser-tests.yml', '--limit', '1', '--json', 'databaseId,status');
  const runs = JSON.parse(list || '[]');
  if (runs.length) runId = runs[0].databaseId;
}

if (!runId) {
  console.log('no run showed up — check Actions is enabled for this repo');
  process.exit(1);
}

console.log(`watching run ${runId}…`);
for (;;) {
  const view = JSON.parse(gh('run', 'view', String(runId), '--json', 'status,conclusion,jobs'));
  const done = view.status === 'completed';
  const running = (view.jobs || []).filter((j) => j.status === 'in_progress').map((j) => `${j.name}`);
  console.log(`  ${view.status}${running.length ? ` — ${running.join(', ')}` : ''}`);
  if (done) {
    console.log(`conclusion: ${view.conclusion}`);
    break;
  }
  await sleep(15000);
}

// Results live on their own branch (force-pushed per run); test-output/ is
// gitignored on the working branch, so take them from there explicitly.
try {
  git('fetch', '-q', 'origin', 'test-results');
  git('checkout', 'FETCH_HEAD', '--', 'test-output');
  console.log('results pulled into test-output/ — open test-output/SUMMARY.md');
} catch (error) {
  console.log('could not pull results:', error.message.split('\n')[0]);
  process.exit(1);
}
