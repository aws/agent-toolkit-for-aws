import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmod, lstat, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { assessFinding, matchLocation, parseLocations, snippetIdentity } from '../check-current-code.mjs';

const finding = (vulnerableCode, filePath = 'app.js', lineNumber = 1) => ({ filePath, lineNumber, vulnerableCode, createdAt: '2026-01-01' });
const script = fileURLToPath(new URL('../check-current-code.mjs', import.meta.url));
async function sourceTree(t) {
  const root = await mkdtemp(join(tmpdir(), 'continuum-code-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  return root;
}

test('identity strips presentation but preserves indentation, inner whitespace and punctuation', () => {
  const identity = code => snippetIdentity(finding(code));
  assert.equal(identity('1: if (admin) {\r\n2 |   grant();  \r\n3: }'), identity('```js\napp.js:90-92\n90 if (admin) {\n91   grant();\n92 }\n```'));
  assert.notEqual(identity('if is_admin:\n    log_access()\ngrant_access()'), identity('if is_admin:\n    log_access()\n    grant_access()'), 'different Python control flow must stay separate');
  assert.notEqual(identity('if (role === "super user") grantAccess();'), identity('if (role === "superuser") grantAccess();'), 'string contents must stay separate');
  assert.notEqual(identity('grant(input);'), identity('grant( input );'), 'inner whitespace is not presentation');
  assert.notEqual(identity('message = """super\n\nuser"""'), identity('message = """super\nuser"""'), 'blank lines inside multiline strings are not presentation');
  assert.notEqual(identity('grant();\n}'), identity('grant();\n{'));
  assert.notEqual(identity('grant();'), snippetIdentity(finding('grant();', 'other.js')));
  assert.equal(identity(''), null);
  assert.equal(snippetIdentity(finding('grant();', '../outside.js')), null);
});

test('moved brace requires review even when all fuzzy needles match', async t => {
  const root = await sourceTree(t);
  await writeFile(join(root, 'app.js'), 'if (isAdmin)\n{\n  grantAccess();\n}');
  const result = await assessFinding(finding('if (isAdmin)\n{\n}\n  grantAccess();'), root);
  assert.equal(result.state, 'Needs review');
  assert.equal(result.locations[0].unchanged, false);
  assert.equal(result.locations[0].ratio, 1, 'fuzzy matching only locates evidence');
  assert.notEqual(result.basis, 'code unchanged');
});

test('exact positional matches are Open; changed, inserted and moved code needs review', async t => {
  const root = await sourceTree(t);
  const value = finding('1: if (admin) {\n2 |   grant();\n3: }');
  for (const [source, state] of [
    ['if (admin) {\r\n  grant();  \r\n}', 'Open'],
    ['if (admin) {\n  deny();\n}', 'Needs review'],
    ['if (admin) {\n  log();\n  grant();\n}', 'Needs review'],
    ['if (admin) {\n}\n  grant();', 'Needs review'],
    ['\nif (admin) {\n  grant();\n}', 'Needs review']
  ]) {
    await writeFile(join(root, 'app.js'), source);
    const result = await assessFinding(value, root);
    assert.equal(result.state, state, source);
    if (state === 'Open') assert.equal(result.basis, 'code unchanged');
  }
});

test('all non-blank lines keep cited offsets; broad labels do not extend the excerpt', () => {
  const check = (code, source) => matchLocation(parseLocations(code, 'app.js')[0], source);
  assert.equal(check('app.js:10-80\na();\nb();', '\n'.repeat(9) + 'a();\nb();\nfollowing();').unchanged, true);
  assert.equal(check('a();\n\nb();', 'a();\nb();').unchanged, false);
  assert.equal(check('\n{\na();\n}', '\n{\na();\n}').unchanged, true);
  assert.equal(check('{\n}', '}\n{').unchanged, false, 'punctuation-only excerpts are checked');
  for (const gap of ['...', '…']) {
    const location = parseLocations(`a();\n${gap}\nb();`, 'app.js')[0];
    assert.deepEqual(location.lines, ['a();', 'b();']);
    assert.equal(matchLocation(location, 'a();\nextra();\nb();').unchanged, true);
    assert.equal(matchLocation(location, 'a();\nextra();\nmore();\nb();').unchanged, false);
  }
  const moved = check('a();\nb();', '\n'.repeat(250) + 'a();\nb();');
  assert.equal(moved.unchanged, false);
  assert.equal(moved.status, 'moved');
  assert.deepEqual(moved.range, { start: 251, end: 252 });
});

test('multi-location findings require an exact match in every file', async t => {
  const root = await sourceTree(t);
  await writeFile(join(root, 'app.js'), 'unsafe();');
  await writeFile(join(root, 'view.html'), '<div>{{ unsafe }}</div>');
  const value = finding('app.js:1\nunsafe();\nview.html:1\n<div>{{ unsafe }}</div>');
  assert.equal((await assessFinding(value, root)).state, 'Open');
  await writeFile(join(root, 'app.js'), 'safe();');
  const result = await assessFinding(value, root);
  assert.equal(result.state, 'Needs review');
  assert.equal(result.locations[1].unchanged, true);
});

test('missing, unsafe and unreadable paths never become code-unchanged Open', async t => {
  const root = await sourceTree(t);
  for (const path of ['missing.js', '../outside.js', '/etc/passwd', 'C:\\outside.js', '.']) {
    const result = await assessFinding(finding('unsafe();', path), root);
    assert.equal(result.state, 'Needs review', path);
    assert.notEqual(result.basis, 'code unchanged');
    assert.equal(result.locations[0].range, null);
  }
});

test('broken and escaping symlinks require review', { skip: process.platform === 'win32' }, async t => {
  const root = await sourceTree(t);
  const outside = await sourceTree(t);
  await writeFile(join(outside, 'app.js'), 'unsafe();');
  await symlink(join(root, 'missing.js'), join(root, 'broken.js'));
  await symlink(join(outside, 'app.js'), join(root, 'escape.js'));
  for (const path of ['broken.js', 'escape.js']) {
    const result = await assessFinding(finding('unsafe();', path), root);
    assert.equal(result.state, 'Needs review');
    assert.notEqual(result.basis, 'code unchanged');
    assert.equal(result.locations[0].range, null);
    if (path === 'escape.js') assert.equal(result.locations[0].status, 'unsafe path');
  }
});

test('no source or snippet retains explicitly unchecked scan-only Open', async t => {
  const root = await sourceTree(t);
  for (const [value, source] of [[finding('unsafe();'), null], [finding('unsafe();'), join(root, 'absent')], [finding(''), root]]) {
    const result = await assessFinding(value, source);
    assert.equal(result.state, 'Open');
    assert.match(result.basis, /not checked against code/);
  }
});

test('checker output is owner-only and refuses symlink targets', { skip: process.platform === 'win32' }, async t => {
  const root = await sourceTree(t);
  const input = join(root, 'findings.json'), output = join(root, 'assessments.json'), victim = join(root, 'victim.txt');
  const run = () => spawnSync(process.execPath, [script, input, '-', output], { encoding: 'utf8', timeout: 20000 });
  await writeFile(input, JSON.stringify([finding('unsafe();')]));
  await writeFile(output, '[]');
  await chmod(output, 0o644);
  let result = run();
  assert.equal(result.status, 0, result.stderr);
  assert.equal((await lstat(output)).mode & 0o777, 0o600);
  await rm(output);
  await writeFile(victim, 'keep');
  await symlink(victim, output);
  result = run();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /not a regular file/);
  assert.equal(await readFile(victim, 'utf8'), 'keep');
});
