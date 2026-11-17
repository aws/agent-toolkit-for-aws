#!/usr/bin/env node
// Repeatable offline evidence check only. No network or repository code execution.
import { lstat, readFile, realpath, rename, stat, unlink, writeFile } from 'node:fs/promises';
import { basename, dirname, join, resolve, relative, isAbsolute } from 'node:path';
import { pathToFileURL } from 'node:url';
import { randomBytes } from 'node:crypto';

const compact = text => text.replace(/\s+/g, '');
// Remove the presentation token and one separator, not the code's indentation.
// A delimiterless padded gutter is indistinguishable from code indentation.
// Keep the extra whitespace: ambiguity needs agent review, not guessed Open.
const stripNumber = line => line.replace(/^\s*\d+(?:[ \t]*[:|][ \t]?|[ \t])/, '');
const significant = line => /[\p{L}\p{N}_]/u.test(line) && !/^\s*(?:\.{3}|…)(?:\s|$)/.test(line);
const safePath = path => path && !isAbsolute(path) && !/^[A-Za-z]:/.test(path) && !path.split(/[\\/]/).includes('..');
const inside = (root, path) => { const rel = relative(root, path); return !isAbsolute(rel) && rel !== '..' && !rel.startsWith('../'); };

export function parseLocations(snippet, filePath, lineNumber = 1) {
  const locations = [];
  let block = { path: filePath, start: Number(lineNumber) || 1, end: Number(lineNumber) || 1, lines: [] };
  function finish() {
    const clean = block.lines.map(stripNumber);
    const lines = clean.filter(significant).map(compact);
    if (lines.length) locations.push({ path: block.path?.replace(/\\/g, '/').replace(/^\.\//, ''), start: block.start, end: Math.max(block.end, block.start + clean.length - 1), lines, firstSignificantLine: block.start + clean.findIndex(significant), exactLines: clean.filter(significant), identityLines: clean.map(compact).filter(Boolean) });
  }
  for (const raw of String(snippet || '').split(/\r?\n/)) {
    if (/^\s*```/.test(raw)) continue;
    const label = raw.trim().replace(/^`|`$/g, '').match(/^(.+?):(\d+)(?:-(\d+))?\s*(?:\([^)]*\))?\s*:?$/);
    if (label) { finish(); block = { path: label[1], start: Number(label[2]), end: Number(label[3] || label[2]), lines: [] }; }
    else block.lines.push(raw);
  }
  finish();
  return locations;
}

// Identity ignores presentation line numbers, but includes every location's path
// and significant code in order. Empty or unsafe evidence can never merge flaws.
export function snippetIdentity(finding) {
  const locations = parseLocations(finding.vulnerableCode, finding.filePath, finding.lineNumber);
  if (!locations.length || locations.some(loc => !safePath(loc.path))) return null;
  return JSON.stringify([finding.filePath?.replace(/\\/g, '/').replace(/^\.\//, ''), locations.map(loc => [loc.path, loc.identityLines])]);
}

// Fuzzy windows only locate evidence for the agent. They never decide a fix.
// Automatic Open requires every significant line unchanged at its cited position,
// with no intervening significant lines inserted or reordered.
export function matchLocation(location, source, tolerance = 40) {
  const raw = source.split(/\r?\n/), lines = raw.map(compact);
  const span = Math.max(location.end - location.start + 1, location.lines.length) + 2 * tolerance;
  function match(start, end) {
    let cursor = start;
    const indices = [];
    for (const needle of location.lines) {
      let at = cursor;
      while (at < end && lines[at] !== needle) at++;
      if (at < end) { indices.push(at); cursor = at + 1; }
    }
    return { ratio: indices.length / location.lines.length, range: indices.length ? { start: indices[0] + 1, end: indices.at(-1) + 1 } : null };
  }
  const start = Math.max(0, location.start - 1 - tolerance);
  let best = match(start, Math.min(lines.length, start + span));
  const candidates = new Set(location.lines);
  for (let i = 0; i < lines.length && best.ratio < 1; i++) {
    if (!candidates.has(lines[i])) continue;
    const candidate = match(i, Math.min(lines.length, i + span));
    if (candidate.ratio > best.ratio) best = candidate;
  }
  // Presentation blanks and broad range labels must not pull following code
  // into the comparison. Compare exactly the excerpt's significant-line count.
  const exact = [];
  for (let i = location.firstSignificantLine - 1; i < raw.length && exact.length < location.exactLines.length; i++) {
    if (significant(raw[i])) exact.push(raw[i]);
  }
  const unchanged = raw[location.firstSignificantLine - 1] === location.exactLines[0] && exact.length === location.exactLines.length && exact.every((line, i) => line === location.exactLines[i]);
  return { ...best, unchanged, status: unchanged ? 'unchanged' : best.ratio === 1 && best.range?.start !== location.firstSignificantLine ? 'moved' : 'partly matched' };
}

export async function assessFinding(finding, sourceRoot = null) {
  const lastSeen = String(finding.createdAt || finding.reportedAt || '').slice(0, 10) || 'date unavailable';
  const unchecked = locations => ({ state: 'Open', basis: `last seen ${lastSeen}; not checked against code`, locations });
  const locations = parseLocations(finding.vulnerableCode, finding.filePath, finding.lineNumber);
  if (!sourceRoot || !locations.length) return unchecked([]);
  let root;
  try { root = await realpath(sourceRoot); if (!(await stat(root)).isDirectory()) return unchecked([]); }
  catch { return unchecked([]); }
  const checks = [];
  for (const location of locations) {
    if (!safePath(location.path)) { checks.push({ ...location, status: 'unsafe path', ratio: null, range: null }); continue; }
    const file = resolve(root, location.path);
    try {
      const actual = await realpath(file);
      if (!inside(root, actual)) { checks.push({ ...location, status: 'unsafe path', reason: 'escaping symlink', ratio: null, range: null }); continue; }
      checks.push({ ...location, ...matchLocation(location, await readFile(actual, 'utf8')) });
    } catch (error) {
      // A broken or escaping ancestor is not proof of deletion. Verify the
      // nearest existing parent is a readable directory within the root.
      let parent = resolve(file, '..'), deletion = error.code === 'ENOENT', unsafe = false;
      while (deletion) {
        try { const actual = await realpath(parent); unsafe = !inside(root, actual); deletion = !unsafe && (await stat(actual)).isDirectory(); break; }
        catch (ancestor) { if (ancestor.code !== 'ENOENT' || parent === root) { deletion = false; break; } parent = resolve(parent, '..'); }
      }
      checks.push({ ...location, status: unsafe ? 'unsafe path' : deletion ? 'file deleted' : 'unreadable', reason: error.code || 'unknown read failure', ratio: deletion ? 0 : null, range: null });
    }
  }
  if (checks.every(loc => loc.unchanged)) return { state: 'Open', basis: 'code unchanged', locations: checks };
  return { state: 'Needs review', basis: 'current code differs or could not be checked', reason: 'Read every cited file around its best-matching range and inspect available git history. Assess the current vulnerability, not the match ratio; when unsure, keep Open.', locations: checks };
}

// Owner-only output (0600), written beside the target and renamed into place so an
// existing symlink or hard link at the target is never written through.
export async function writePrivate(path, data) {
  const existing = await lstat(path).catch(error => { if (error.code === 'ENOENT') return null; throw error; });
  if (existing && !existing.isFile()) throw new Error(`Refusing to replace ${path}: it is not a regular file.`);
  const temporary = join(dirname(path), `.${basename(path)}.${randomBytes(8).toString('hex')}.tmp`);
  await writeFile(temporary, data, { mode: 0o600, flag: 'wx' });
  try { await rename(temporary, path); }
  catch (error) { await unlink(temporary).catch(() => {}); throw error; }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const [input, root, output] = process.argv.slice(2);
    if (!input || !root || !output || process.argv.length !== 5) throw new Error('usage: check-current-code.mjs newest-findings.json source-root-or-dash assessments.json');
    const findings = JSON.parse(await readFile(input, 'utf8'));
    if (!Array.isArray(findings)) throw new Error('Expected an array of newest finding records.');
    const results = [];
    for (const finding of findings) results.push({ findingId: finding.findingId, ...await assessFinding(finding, root === '-' ? null : root) });
    await writePrivate(resolve(output), JSON.stringify(results, null, 2) + '\n');
  } catch (error) { console.error('error: ' + error.message); process.exitCode = 1; }
}
