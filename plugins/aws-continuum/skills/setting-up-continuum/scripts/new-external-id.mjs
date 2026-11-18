#!/usr/bin/env node
// Generate the caller-provided external ID for a new Continuum integration role.
// Usage: node new-external-id.mjs [trust-policy.json]
// Prints a 256-bit random ID (64 hex characters) from the Node CSPRNG. With a path,
// also writes the integration role trust policy using that ID, owner-only (0600),
// refusing to replace an existing file. No network, AWS or repository access.
import { randomBytes } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

// IAM accepts 2-1224 characters of [\w+=,.@:/-] for sts:ExternalId; hex fits.
export const newExternalId = () => randomBytes(32).toString('hex');

export function trustPolicy(externalId) {
  if (!/^[a-f0-9]{64}$/.test(externalId)) throw new Error('Expected a generated 64-character hex external ID.');
  return { Version: '2012-10-17', Statement: [{ Sid: 'ContinuumSourceAccess', Effect: 'Allow', Principal: { Service: 'continuum.amazonaws.com' }, Action: 'sts:AssumeRole', Condition: { StringEquals: { 'sts:ExternalId': externalId } } }] };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const args = process.argv.slice(2);
    if (args.length > 1 || args[0]?.startsWith('-')) throw new Error('usage: new-external-id.mjs [trust-policy.json]');
    const externalId = newExternalId();
    // 'wx' fails if the path exists, including a symlink, so nothing is overwritten or written through.
    if (args[0]) await writeFile(resolve(args[0]), JSON.stringify(trustPolicy(externalId), null, 2) + '\n', { mode: 0o600, flag: 'wx' });
    console.log(externalId);
  } catch (error) { console.error('error: ' + error.message); process.exitCode = 1; }
}
