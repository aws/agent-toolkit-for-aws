import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, rm, stat, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { newExternalId, trustPolicy } from '../new-external-id.mjs';

const script = fileURLToPath(new URL('../new-external-id.mjs', import.meta.url));
const run = (...args) => spawnSync(process.execPath, [script, ...args], { encoding: 'utf8', timeout: 20000 });

test('external IDs are 256-bit hex, valid for sts:ExternalId, and do not repeat', () => {
  const ids = Array.from({ length: 1000 }, newExternalId);
  for (const id of ids) assert.match(id, /^[a-f0-9]{64}$/);
  assert.equal(new Set(ids).size, ids.length);
});

test('trust policy matches the public getting-started shape and rejects non-generated IDs', () => {
  const id = newExternalId();
  assert.deepEqual(trustPolicy(id).Statement[0], { Sid: 'ContinuumSourceAccess', Effect: 'Allow', Principal: { Service: 'continuum.amazonaws.com' }, Action: 'sts:AssumeRole', Condition: { StringEquals: { 'sts:ExternalId': id } } });
  for (const guessable of ['continuum-myrepo-2026', '', 'A'.repeat(64)]) assert.throws(() => trustPolicy(guessable));
});

test('CLI prints the ID and writes an owner-only trust policy with the same ID', { skip: process.platform === 'win32' }, async () => {
  const dir = await mkdtemp(join(tmpdir(), 'continuum-external-id-'));
  try {
    const out = join(dir, 'trust.json');
    const result = run(out);
    assert.equal(result.status, 0, result.stderr);
    const id = result.stdout.trim();
    assert.match(id, /^[a-f0-9]{64}$/);
    assert.equal((await stat(out)).mode & 0o777, 0o600);
    assert.equal(JSON.parse(await readFile(out, 'utf8')).Statement[0].Condition.StringEquals['sts:ExternalId'], id);
    assert.match(run().stdout, /^[a-f0-9]{64}\n$/, 'no path prints only the ID');
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('CLI refuses existing files and symlinks and leaves them untouched', { skip: process.platform === 'win32' }, async () => {
  const dir = await mkdtemp(join(tmpdir(), 'continuum-external-id-'));
  try {
    const existing = join(dir, 'trust.json'), victim = join(dir, 'victim.txt'), link = join(dir, 'link.json');
    await writeFile(existing, 'keep'); await writeFile(victim, 'keep'); await symlink(victim, link);
    for (const path of [existing, link]) {
      const result = run(path);
      assert.equal(result.status, 1);
      assert.equal(result.stdout, '', 'no ID is printed when the policy was not written');
    }
    assert.equal(await readFile(existing, 'utf8'), 'keep');
    assert.equal(await readFile(victim, 'utf8'), 'keep');
    assert.equal(run('a', 'b').status, 1);
    assert.equal(run('--help').status, 1);
  } finally { await rm(dir, { recursive: true, force: true }); }
});
