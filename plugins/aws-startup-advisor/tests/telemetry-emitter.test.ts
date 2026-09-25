// Executing-path tests for the telemetry emitter (scripts/telemetry/emit.mjs).
//
// Each test builds an ephemeral project with a .migration/ run and a consent
// record, points the emitter at a local HTTP stub, runs it exactly as a hook
// would (node emit.mjs --reconcile, hook payload on stdin) and asserts on the
// requests the stub received and the snapshot left on disk. Nothing inside the
// emitter is mocked.
//
// Run: node --test tests/telemetry-emitter.test.ts (from the plugin root) or mise run test

import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, utimesSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { readFileSync as readText } from 'node:fs';
import { tmpdir } from 'node:os';

const EMIT = join(import.meta.dirname, '../scripts/telemetry/emit.mjs');
const RUN_ID = '3f9c2a7e-5b1d-4e8a-9c6f-2d7b8e1a4c53';
const SESSION_ID = '9b2c4d6e-8f10-4a12-b345-6789abcdef01';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Received = { body: any };

let server: Server;
let endpoint: string;
const received: Received[] = [];
// What the stub answers; a test flips it to 403 or 429 to stand in for the
// service's closed launch gate or a throttle, or decides per request body.
let respondWith = 200;
let respondFor: (body: any) => number = () => respondWith;
// How long the stub waits before answering; a test raises it to stand in for a
// slow network.
let delayFor: (body: any) => number = () => 0;

before(async () => {
  server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      received.push({ body });
      setTimeout(() => res.writeHead(respondFor(body)).end(), delayFor(body));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  endpoint = `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1/plugin-telemetry-event`;
});

after(() => server.close());

interface Project {
  root: string;
  runDir: string;
  stateDir: string;
  statusFile: string;
  consentFile: string;
}

function phaseStatus(overrides: Record<string, unknown> = {}) {
  return {
    migration_id: '0226-1430',
    run_id: RUN_ID,
    owning_skill: 'GCP_TO_AWS',
    last_updated: '2026-02-26T15:35:22Z',
    current_phase: 'clarify',
    phases: {
      discover: 'completed',
      clarify: 'in_progress',
      design: 'pending',
      estimate: 'pending',
      workshop: 'pending',
      generate: 'pending',
      feedback: 'pending',
    },
    ...overrides,
  };
}

// What Discover leaves behind in an ordinary GCP run; the source platform is
// read from it.
const GCP_INVENTORY = { resources: [{ type: 'cloud_run' }, { type: 'cloud_sql' }] };

// Consent is written before the state file, the order `_init` uses (run
// directory, consent, then phase status), so the run reads as live rather than
// as pre-consent history. Artifacts are the run's own JSON files, by name.
function makeProject(
  status: Record<string, unknown>,
  consent: 'granted' | 'revoked' | null = 'granted',
  artifacts: Record<string, unknown> = { 'gcp-resource-inventory.json': GCP_INVENTORY },
): Project {
  const root = mkdtempSync(join(tmpdir(), 'emit-project-'));
  const runDir = join(root, '.migration', '0226-1430');
  mkdirSync(runDir, { recursive: true });
  const consentFile = join(root, '.migration', 'telemetry.json');
  if (consent) writeConsent(consentFile, consent);
  for (const [name, value] of Object.entries(artifacts)) writeFileSync(join(runDir, name), JSON.stringify(value));
  const statusFile = join(runDir, '.phase-status.json');
  writeFileSync(statusFile, JSON.stringify(status, null, 2));
  return { root, runDir, stateDir: mkdtempSync(join(tmpdir(), 'emit-state-')), statusFile, consentFile };
}

function writeConsent(file: string, consent: 'granted' | 'revoked', consentedAt = new Date()) {
  writeFileSync(file, JSON.stringify({ consent, installId: RUN_ID, consentedAt: consentedAt.toISOString(), version: 1 }));
}

function cleanup(p: Project) {
  rmSync(p.root, { recursive: true, force: true });
  rmSync(p.stateDir, { recursive: true, force: true });
}

function hostEnv(p: Project) {
  const env = { ...process.env };
  delete env.DO_NOT_TRACK;
  delete env.AWS_STARTUP_ADVISOR_TELEMETRY;
  delete env.CURSOR_VERSION;
  delete env.CURSOR_PROJECT_DIR;
  return Object.assign(env, {
    AWS_STARTUP_ADVISOR_TELEMETRY_ENDPOINT: endpoint,
    CLAUDE_PLUGIN_DATA: p.stateDir,
    CLAUDECODE: '1',
  });
}

// Run the emitter the way a hook does (payload on stdin) and return only the
// requests this invocation produced.
async function run(p: Project, args: string[], payload: Record<string, unknown>): Promise<any[]> {
  const before = received.length;
  const child = spawn(process.execPath, [EMIT, ...args], { cwd: p.root, env: hostEnv(p), stdio: ['pipe', 'ignore', 'inherit'] });
  child.stdin.end(JSON.stringify(payload));
  const code = await new Promise<number | null>((resolve) => child.on('close', resolve));
  assert.equal(code, 0, 'the emitter is fail-open and always exits 0');
  return received.slice(before).map((r) => r.body);
}

const reconcile = (p: Project, sessionId = SESSION_ID) => run(p, ['--reconcile'], { session_id: sessionId, cwd: p.root });
const sessionEnd = (p: Project, sessionId = SESSION_ID) =>
  run(p, ['--session-end'], { session_id: sessionId, cwd: p.root, reason: 'other' });

// Run the consent command the way the skill instructions do, from the project
// root, and return what it printed.
async function consent(p: Project, action: string): Promise<string> {
  const child = spawn(process.execPath, [EMIT, 'consent', action], { cwd: p.root, env: hostEnv(p), stdio: ['ignore', 'pipe', 'inherit'] });
  let out = '';
  child.stdout.on('data', (chunk) => (out += chunk));
  await new Promise((resolve) => child.on('close', resolve));
  return out.trim();
}

const activity = (body: any) => body.pluginTelemetryEvent.migrationActivity;
const snapshotOf = (p: Project) => JSON.parse(readFileSync(join(p.runDir, '.telemetry-snapshot.json'), 'utf8'));

describe('telemetry emitter', () => {
  it('reports a new run once: RUN_STARTED plus the phases already resolved, under the state file run_id', async () => {
    // Arrange
    const p = makeProject(phaseStatus());
    try {
      // Act
      const first = await reconcile(p);
      const second = await reconcile(p);

      // Assert
      assert.deepEqual(
        first.map((b) => [activity(b).eventName, activity(b).phase, activity(b).status]).sort(),
        [
          ['PHASE_COMPLETED', 'DISCOVER', 'SUCCESS'],
          ['RUN_STARTED', undefined, undefined],
        ],
      );
      for (const body of first) {
        assert.equal(activity(body).runId, RUN_ID);
        assert.equal(activity(body).skill, 'GCP_TO_AWS');
        assert.equal(activity(body).sessionId, SESSION_ID);
        assert.equal(body.source, 'CLAUDE_CODE');
        assert.match(body.installId, UUID);
        assert.equal(typeof body.occurredAt, 'number');
        assert.equal(activity(body).attributes?.sourceProvider, 'GCP');
      }
      assert.deepEqual(second, [], 'an unchanged run is not re-reported');
      assert.equal(snapshotOf(p).runId, RUN_ID);
    } finally {
      cleanup(p);
    }
  });

  it('sends a run_id that macOS uuidgen minted in upper case in lower case, the only form the data lake accepts', async () => {
    // Arrange
    const p = makeProject(phaseStatus({ run_id: RUN_ID.toUpperCase() }));
    try {
      // Act
      const bodies = await reconcile(p);

      // Assert
      assert.equal(bodies.length, 2);
      for (const body of bodies) assert.equal(activity(body).runId, RUN_ID);
      assert.equal(snapshotOf(p).runId, RUN_ID);
    } finally {
      cleanup(p);
    }
  });

  it('reports each later transition exactly once and the terminal event with its run mode', async () => {
    // Arrange
    const p = makeProject(phaseStatus());
    try {
      await reconcile(p);
      const status = phaseStatus({
        current_phase: 'complete',
        run_mode: 'decide',
        phases: { ...phaseStatus().phases, clarify: 'completed', design: 'completed', estimate: 'completed' },
      });
      writeFileSync(p.statusFile, JSON.stringify(status, null, 2));

      // Act
      const events = await reconcile(p);
      const again = await reconcile(p);

      // Assert
      assert.deepEqual(
        events.map((b) => [activity(b).eventName, activity(b).phase ?? activity(b).attributes?.runMode]).sort(),
        [
          ['PHASE_COMPLETED', 'CLARIFY'],
          ['PHASE_COMPLETED', 'DESIGN'],
          ['PHASE_COMPLETED', 'ESTIMATE'],
          ['RUN_COMPLETED', 'DECIDE'],
        ],
      );
      assert.deepEqual(again, []);
      assert.equal(snapshotOf(p).completed, true);
    } finally {
      cleanup(p);
    }
  });

  it('sends nothing and leaves no trace without granted consent', async () => {
    // Arrange
    const revoked = makeProject(phaseStatus(), 'revoked');
    const unset = makeProject(phaseStatus(), null);
    try {
      // Act + Assert
      assert.deepEqual(await reconcile(revoked), []);
      assert.deepEqual(await reconcile(unset), []);
      assert.equal(existsSync(join(revoked.runDir, '.telemetry-snapshot.json')), false);
      assert.equal(existsSync(join(unset.runDir, '.telemetry-snapshot.json')), false);
    } finally {
      cleanup(revoked);
      cleanup(unset);
    }
  });

  it('sends nothing for a run that names no owning skill', async () => {
    // Arrange
    const status = phaseStatus();
    delete (status as Record<string, unknown>).owning_skill;
    const p = makeProject(status);
    try {
      // Act + Assert
      assert.deepEqual(await reconcile(p), []);
    } finally {
      cleanup(p);
    }
  });

  it('reports a run whose state was written moments before consent: a near tie is live, not history', async () => {
    // Arrange: state first, consent 50 ms later, as a slow host or coarse
    // filesystem timestamp would order them
    const p = makeProject(phaseStatus(), null);
    try {
      await new Promise((r) => setTimeout(r, 50));
      writeFileSync(
        p.consentFile,
        JSON.stringify({ consent: 'granted', installId: RUN_ID, consentedAt: new Date().toISOString(), version: 1 }),
      );

      // Act
      const events = await reconcile(p);

      // Assert
      assert.equal(events.length, 2, 'RUN_STARTED and DISCOVER are reported');
    } finally {
      cleanup(p);
    }
  });

  it('holds the snapshot while the service refuses with 403, then reports the run in full once it accepts', async () => {
    // Arrange
    const p = makeProject(phaseStatus());
    try {
      // Act: the gate is closed for the first reconcile and open for the second
      respondWith = 403;
      const refused = await reconcile(p);
      const snapshotWhileRefused = existsSync(join(p.runDir, '.telemetry-snapshot.json'));
      respondWith = 200;
      const accepted = await reconcile(p);
      const again = await reconcile(p);

      // Assert
      assert.equal(refused.length, 2, 'the events were attempted');
      assert.equal(snapshotWhileRefused, false, 'but nothing was recorded as reported');
      assert.deepEqual(
        accepted.map((b) => [activity(b).eventName, activity(b).phase]).sort(),
        [['PHASE_COMPLETED', 'DISCOVER'], ['RUN_STARTED', undefined]],
        'the same events are sent again once accepted',
      );
      assert.deepEqual(again, []);
      assert.equal(snapshotOf(p).runId, RUN_ID);
    } finally {
      respondWith = 200;
      cleanup(p);
    }
  });

  it('re-sends only the throttled events of a batch, never the accepted ones', async () => {
    // Arrange: RUN_STARTED is accepted, the phase event in the same batch gets a 429
    const p = makeProject(phaseStatus());
    try {
      respondFor = (body) => (activity(body).eventName === 'PHASE_COMPLETED' ? 429 : 200);
      const first = await reconcile(p);
      respondFor = () => 200;

      // Act
      const replay = await reconcile(p);
      const again = await reconcile(p);

      // Assert
      assert.equal(first.length, 2, 'both were attempted');
      assert.deepEqual(
        replay.map((b) => [activity(b).eventName, activity(b).phase]),
        [['PHASE_COMPLETED', 'DISCOVER']],
        'only the throttled event is sent again',
      );
      assert.deepEqual(again, []);
      assert.equal(snapshotOf(p).phases.discover, 'completed');
    } finally {
      respondFor = () => respondWith;
      cleanup(p);
    }
  });

  it('re-sends RUN_STARTED alone when it was the one refused', async () => {
    // Arrange: the phase event is accepted, RUN_STARTED gets a 503
    const p = makeProject(phaseStatus());
    try {
      respondFor = (body) => (activity(body).eventName === 'RUN_STARTED' ? 503 : 200);
      await reconcile(p);
      respondFor = () => 200;

      // Act
      const replay = await reconcile(p);

      // Assert
      assert.deepEqual(replay.map((b) => activity(b).eventName), ['RUN_STARTED']);
      assert.equal(snapshotOf(p).started, true);
    } finally {
      respondFor = () => respondWith;
      cleanup(p);
    }
  });

  it('lets a recorded no anywhere win, and a plugin-wide yes stand in for a missing project one', async () => {
    // Arrange: no project consent, but the plugin-wide record (in the plugin data dir) says granted
    const granted = makeProject(phaseStatus(), null);
    writeConsent(join(granted.stateDir, 'telemetry.json'), 'granted', new Date(Date.now() - 60_000));
    // a project that said yes while the plugin-wide record says no
    const overruled = makeProject(phaseStatus(), 'granted');
    writeConsent(join(overruled.stateDir, 'telemetry.json'), 'revoked');
    // and a project whose stop-sharing command ran under a plugin-wide yes
    const stopped = makeProject(phaseStatus(), null);
    writeConsent(join(stopped.stateDir, 'telemetry.json'), 'granted', new Date(Date.now() - 60_000));
    try {
      // Act
      const revoke = await consent(stopped, 'revoke');
      const get = await consent(stopped, 'get');

      // Assert
      assert.equal((await reconcile(granted)).length, 2, 'plugin-wide yes is enough');
      assert.deepEqual(await reconcile(overruled), [], 'plugin-wide no wins over a project yes');
      assert.equal(revoke, 'revoked');
      assert.equal(get, 'revoked', 'the project decision is the effective one');
      assert.deepEqual(await reconcile(stopped), [], 'and the hook sends nothing under a plugin-wide yes');
      assert.equal(existsSync(join(stopped.runDir, '.telemetry-snapshot.json')), false);
    } finally {
      cleanup(granted);
      cleanup(overruled);
      cleanup(stopped);
    }
  });

  it('treats a run last written before consent as history: baselines it silently, then reports only new transitions', async () => {
    // Arrange: the state file predates the consent record by a day
    const p = makeProject(phaseStatus());
    const dayAgo = new Date(Date.now() - 24 * 3600 * 1000);
    utimesSync(p.statusFile, dayAgo, dayAgo);
    try {
      // Act
      const first = await reconcile(p);
      writeFileSync(
        p.statusFile,
        JSON.stringify(phaseStatus({ current_phase: 'design', phases: { ...phaseStatus().phases, clarify: 'completed' } }), null, 2),
      );
      const later = await reconcile(p);

      // Assert
      assert.deepEqual(first, [], 'pre-consent history is not reported');
      assert.deepEqual(snapshotOf(p).phases.discover, 'completed', 'but it is recorded as already known');
      assert.deepEqual(
        later.map((b) => [activity(b).eventName, activity(b).phase]),
        [['PHASE_COMPLETED', 'CLARIFY']],
        'no RUN_STARTED is invented for a run that started before consent',
      );
    } finally {
      cleanup(p);
    }
  });

  it('never reports transitions made while consent was revoked, even after a new grant', async () => {
    // Arrange: a reported run; consent is withdrawn, CLARIFY completes meanwhile,
    // consent is granted again later, then DESIGN completes
    const p = makeProject(phaseStatus());
    const withPhases = (phases: Record<string, string>, current_phase: string) =>
      phaseStatus({ current_phase, phases: { ...phaseStatus().phases, ...phases } });
    try {
      await reconcile(p);
      writeConsent(p.consentFile, 'revoked');
      writeFileSync(p.statusFile, JSON.stringify(withPhases({ clarify: 'completed' }, 'design'), null, 2));
      const tenSecondsAgo = new Date(Date.now() - 10_000);
      utimesSync(p.statusFile, tenSecondsAgo, tenSecondsAgo);
      const whileRevoked = await reconcile(p);
      writeConsent(p.consentFile, 'granted');

      // Act
      const afterRegrant = await reconcile(p);
      writeFileSync(
        p.statusFile,
        JSON.stringify(withPhases({ clarify: 'completed', design: 'completed' }, 'estimate'), null, 2),
      );
      const next = await reconcile(p);

      // Assert
      assert.deepEqual(whileRevoked, []);
      assert.deepEqual(afterRegrant, [], 'the phase completed during revocation stays unreported');
      assert.equal(snapshotOf(p).phases.clarify, 'completed', 'but is recorded as known');
      assert.deepEqual(
        next.map((b) => [activity(b).eventName, activity(b).phase, activity(b).runId]),
        [['PHASE_COMPLETED', 'DESIGN', RUN_ID]],
        'the next consented transition is reported once, under the same run',
      );
    } finally {
      cleanup(p);
    }
  });

  it('reports a phase that completes again after a confirmed re-entry reset, exactly once more', async () => {
    // Arrange: DISCOVER was reported; the interpreter resets it to in_progress
    // for a re-run, then it completes again
    const p = makeProject(phaseStatus());
    try {
      await reconcile(p);
      writeFileSync(
        p.statusFile,
        JSON.stringify(phaseStatus({ current_phase: 'discover', phases: { ...phaseStatus().phases, discover: 'in_progress' } }), null, 2),
      );

      // Act
      const duringRerun = await reconcile(p);
      const observed = snapshotOf(p).phases.discover;
      writeFileSync(p.statusFile, JSON.stringify(phaseStatus(), null, 2));
      const completedAgain = await reconcile(p);
      const again = await reconcile(p);

      // Assert
      assert.deepEqual(duringRerun, [], 'a reset itself is not an event');
      assert.equal(observed, 'in_progress', 'but it is recorded');
      assert.deepEqual(
        completedAgain.map((b) => [activity(b).eventName, activity(b).phase, activity(b).status]),
        [['PHASE_COMPLETED', 'DISCOVER', 'SUCCESS']],
      );
      assert.deepEqual(again, []);
    } finally {
      cleanup(p);
    }
  });

  it('hands a run to the session that last changed it, so that session\'s teardown reports it', async () => {
    // Arrange: session A reported the run; session B resets a phase (an edit
    // the hook sees), then completes it through a shell write the hook does not
    const p = makeProject(phaseStatus());
    const SESSION_B = 'c0ffee00-1111-4222-8333-444455556666';
    try {
      await reconcile(p);
      writeFileSync(
        p.statusFile,
        JSON.stringify(phaseStatus({ current_phase: 'discover', phases: { ...phaseStatus().phases, discover: 'in_progress' } }), null, 2),
      );
      await run(p, [], { session_id: SESSION_B, cwd: p.root, tool_input: { file_path: p.statusFile } });
      const owner = snapshotOf(p).sessionId;
      writeFileSync(p.statusFile, JSON.stringify(phaseStatus(), null, 2));

      // Act
      const byA = await sessionEnd(p, SESSION_ID);
      const byB = await sessionEnd(p, SESSION_B);

      // Assert
      assert.equal(owner, SESSION_B);
      assert.deepEqual(byA, [], 'a session that no longer owns the run leaves it alone');
      assert.deepEqual(byB.map((b) => [activity(b).eventName, activity(b).phase, activity(b).sessionId]), [
        ['PHASE_COMPLETED', 'DISCOVER', SESSION_B],
      ]);
    } finally {
      cleanup(p);
    }
  });

  it('keeps a teardown sweep inside the host budget and never repeats what it attempted', async () => {
    // Arrange: the service answers slower than the SessionEnd budget allows
    const p = makeProject(phaseStatus());
    delayFor = () => 1_900;
    try {
      // Act
      const startedAt = Date.now();
      const attempted = await sessionEnd(p);
      const elapsed = Date.now() - startedAt;
      delayFor = () => 0;
      const later = await reconcile(p);

      // Assert
      assert.equal(attempted.length, 2, 'the events were attempted');
      // The emitter's own deadline is 1.1 s from start; the bound leaves room for
      // a slow runner's process start-up while staying well under the stub's delay.
      assert.ok(elapsed < 1_700, `the sweep finished in ${elapsed} ms, before the 1.9 s response`);
      assert.equal(existsSync(join(p.runDir, '.telemetry-lock')), false, 'the lock was released');
      assert.equal(snapshotOf(p).phases.discover, 'completed', 'and the snapshot was written');
      assert.deepEqual(later, [], 'an attempt cut short is not repeated');
    } finally {
      delayFor = () => 0;
      cleanup(p);
    }
  });

  it('derives attributes from producer-shaped artifacts, including the AI-only route', async () => {
    // Arrange: a completed GCP run with the artifacts Clarify and Estimate write
    const done = (extra: Record<string, unknown> = {}) =>
      phaseStatus({
        current_phase: 'complete',
        phases: { ...phaseStatus().phases, clarify: 'completed', design: 'completed', estimate: 'completed' },
        ...extra,
      });
    const gcp = makeProject(done(), 'granted', {
      'gcp-resource-inventory.json': GCP_INVENTORY,
      'preferences.json': { metadata: { clarify_mode: 'wizard', migration_type: 'full' } },
      'estimation-infra.json': {
        recommendation: { outcome: 'defer_for_evidence' },
        current_costs: { source: 'preferences', gcp_monthly_spend: 2500 },
      },
      'estimation-billing.json': {
        metadata: { estimate_source: 'billing_only', pricing_source: 'cached' },
        gcp_baseline: { source: 'billing_data', total_monthly_spend: 450 },
      },
    });
    // and an AI-only run delegated from llm-to-bedrock: no infrastructure inventory
    const aiOnly = makeProject(done({ initiated_by: 'LLM_TO_BEDROCK' }), 'granted', {
      'ai-workload-profile.json': { summary: { ai_source: 'openai', total_models_detected: 2 } },
      'preferences.json': { metadata: { clarify_mode: 'fast_path', migration_type: 'ai-only' } },
    });
    const mixed = makeProject(done(), 'granted', {
      'ai-workload-profile.json': { summary: { ai_source: 'both', total_models_detected: 2 } },
    });
    const attrs = (bodies: any[], phase: string) =>
      bodies.map(activity).find((a) => a.eventName === 'PHASE_COMPLETED' && a.phase === phase)?.attributes;
    try {
      // Act
      const g = await reconcile(gcp);
      const a = await reconcile(aiOnly);
      const m = await reconcile(mixed);

      // Assert
      assert.deepEqual(attrs(g, 'DISCOVER'), { sourceProvider: 'GCP', resourceCount: 2, hasDatabase: true, hasAi: false });
      assert.deepEqual(attrs(g, 'CLARIFY'), { sourceProvider: 'GCP', clarifyMode: 'WIZARD' });
      assert.deepEqual(attrs(g, 'ESTIMATE'), {
        sourceProvider: 'GCP',
        recommendationOutcome: 'DEFER',
        pricingSource: 'CACHED',
        spendBand: 'FROM_1K_TO_10K',
        spendBasis: 'USER_PROVIDED',
      });
      assert.deepEqual(attrs(a, 'DISCOVER'), { sourceProvider: 'OPENAI', hasAi: true });
      assert.deepEqual(attrs(a, 'CLARIFY'), { sourceProvider: 'OPENAI', clarifyMode: 'AI_ONLY' });
      assert.equal(activity(a[0]).initiatingSkill, 'LLM_TO_BEDROCK');
      assert.equal(attrs(m, 'DISCOVER')?.sourceProvider, undefined, 'two providers is ambiguous: omitted');
    } finally {
      cleanup(gcp);
      cleanup(aiOnly);
      cleanup(mixed);
    }
  });

  it('derives the enriched attributes from the design constraints, estimates and generate artifacts', async () => {
    // Arrange: a completed gcp run with the artifacts the later phases write
    const gcp = makeProject(
      phaseStatus({
        current_phase: 'complete',
        run_mode: 'decide_and_execute',
        phases: {
          discover: 'completed', clarify: 'completed', design: 'completed', estimate: 'completed',
          workshop: 'skipped', generate: 'completed', feedback: 'not_applicable',
        },
      }),
      'granted',
      {
        'gcp-resource-inventory.json': { ...GCP_INVENTORY, summary: { classification_coverage: '97%' } },
        'migration-preview.json': { complexity_signal: 'complex' },
        'preferences.json': {
          metadata: { clarify_mode: 'full', migration_type: 'full' },
          design_constraints: {
            compliance: { value: ['pci-dss', 'soc-2', 'iso27001', 'PCI'] },
            availability: { value: 'multi-az-ha' },
            cutover_strategy: { value: 'zero-downtime' },
            db_size: { value: '10-100 GB' },
            database_traffic: { value: 'read-heavy' },
            kubernetes: { value: 'ecs-fargate' },
            target_region: { value: 'eu-west-1' },
          },
        },
        'estimation-infra.json': {
          recommendation: { outcome: 'conditional_go', confidence: 'medium' },
          current_costs: { source: 'billing_data', gcp_monthly: '380', accuracy: '±5% (billing)' },
          migration_cost_considerations: { billing_data_available: true },
          projected_costs: { pricing_source: 'live', aws_monthly_optimized: 1003.4, aws_monthly_balanced: 1450, aws_monthly_premium: 12_000_000 },
        },
        'generation-infra.json': { complexity_tier: 'medium' },
        'validation-report.json': { status: 'passed_degraded_offline' },
      },
    );
    const byPhase = (bodies: any[]) =>
      Object.fromEntries(bodies.map(activity).map((a) => [a.phase ?? a.eventName, a.attributes]));
    try {
      // Act
      const events = byPhase(await reconcile(gcp));

      // Assert
      assert.deepEqual(events.DISCOVER, {
        sourceProvider: 'GCP', resourceCount: 2, hasDatabase: true, hasAi: false, classificationCoverage: 'NEAR_COMPLETE',
      });
      assert.deepEqual(events.CLARIFY, {
        sourceProvider: 'GCP',
        clarifyMode: 'FULL',
        compliance: ['PCI', 'SOC2'],
        availability: 'MULTI_AZ_HA',
        cutoverStrategy: 'ZERO_DOWNTIME',
        dbSize: 'DB_10_100GB',
        databaseTraffic: 'READ_HEAVY',
        computePosture: 'ECS_FARGATE',
        targetRegion: 'EU_WEST_1',
      });
      assert.deepEqual(events.ESTIMATE, {
        sourceProvider: 'GCP',
        recommendationOutcome: 'CONDITIONAL_GO',
        recommendationConfidence: 'MEDIUM',
        pricingSource: 'LIVE',
        estimateAccuracyBand: 'HIGH',
        billingDataAvailable: true,
        awsProjectedCostOptimized: 1003,
        awsProjectedCostBalanced: 1450,
        spendBand: 'FROM_100_TO_1K',
        spendBasis: 'BILLING_DATA',
        complexityTier: 'MEDIUM',
      }, 'a 12,000,000 premium figure is out of range and omitted, not clamped');
      assert.deepEqual(events.GENERATE, { sourceProvider: 'GCP', validationStatus: 'PASSED_DEGRADED_OFFLINE', complexityTier: 'MEDIUM' });
      assert.deepEqual(events.WORKSHOP, { sourceProvider: 'GCP', complexityTier: 'MEDIUM' }, 'the tier rides every event from DESIGN onward');
      assert.deepEqual(events.RUN_COMPLETED, { sourceProvider: 'GCP', complexityTier: 'MEDIUM', runMode: 'DECIDE_AND_EXECUTE' });
    } finally {
      cleanup(gcp);
    }
  });

  it('falls back to the discover preview for the complexity tier, and to confirmed billing data for the spend basis', async () => {
    // Arrange: DESIGN done, no tiered artifact yet; heroku spend recorded without a source
    const gcp = makeProject(
      phaseStatus({ current_phase: 'estimate', phases: { ...phaseStatus().phases, clarify: 'completed', design: 'completed' } }),
      'granted',
      { 'gcp-resource-inventory.json': GCP_INVENTORY, 'migration-preview.json': { complexity_signal: 'likely_simple' } },
    );
    const heroku = makeProject(
      phaseStatus({ owning_skill: 'HEROKU_TO_AWS', current_phase: 'workshop', phases: { ...phaseStatus().phases, clarify: 'completed', design: 'completed', estimate: 'completed' } }),
      'granted',
      {
        'heroku-resource-inventory.json': { resources: [{ resource_type: 'formation' }] },
        'estimation-infra.json': {
          recommendation: { outcome: 'defer_for_evidence' },
          cost_comparison: { heroku_monthly_baseline: 2200 },
          migration_cost_considerations: { billing_data_available: true },
          estimation_summary: { complexity_tier: 'large' },
        },
      },
    );
    const find = (bodies: any[], phase: string) => bodies.map(activity).find((a) => a.phase === phase)?.attributes;
    try {
      // Act
      const g = await reconcile(gcp);
      const h = await reconcile(heroku);

      // Assert
      assert.deepEqual(find(g, 'DESIGN'), { sourceProvider: 'GCP', complexityTier: 'SMALL' });
      assert.deepEqual(find(h, 'ESTIMATE'), {
        sourceProvider: 'HEROKU',
        recommendationOutcome: 'DEFER',
        billingDataAvailable: true,
        spendBand: 'FROM_1K_TO_10K',
        spendBasis: 'BILLING_DATA',
        complexityTier: 'LARGE',
      });
    } finally {
      cleanup(gcp);
      cleanup(heroku);
    }
  });

  it('detects a Heroku database from the add-on service, not from the resource type', async () => {
    // Arrange: one formation and one Postgres add-on, as heroku discover writes them
    const heroku = (resources: unknown[]) =>
      makeProject(phaseStatus({ owning_skill: 'HEROKU_TO_AWS' }), 'granted', {
        'heroku-resource-inventory.json': { resources },
      });
    const formation = { resource_type: 'formation', config: { command: 'node web.js', dyno_type: 'standard-1x' } };
    const withDb = heroku([formation, { resource_type: 'addon', config: { addon_service: 'heroku-postgresql', plan: 'standard-0' } }]);
    const withoutDb = heroku([formation]);
    const discover = (bodies: any[]) => bodies.map(activity).find((a) => a.phase === 'DISCOVER')?.attributes;
    try {
      // Act + Assert
      assert.deepEqual(discover(await reconcile(withDb)), { sourceProvider: 'HEROKU', resourceCount: 2, hasDatabase: true, hasAi: false });
      assert.deepEqual(discover(await reconcile(withoutDb)), { sourceProvider: 'HEROKU', resourceCount: 1, hasDatabase: false, hasAi: false });
    } finally {
      cleanup(withDb);
      cleanup(withoutDb);
    }
  });
});

// Host registration. Claude Code: both manifests point at the hooks file under
// com.anthropic.claude-code/ (the repository's convention) and every command reaches
// the emitter through ${CLAUDE_PLUGIN_ROOT}. Cursor: the manifest points at the Cursor
// hooks file and every command goes through ${CURSOR_PLUGIN_ROOT}, the form Cursor's
// own plugins use; a plugin-root-relative path is not documented to resolve.
describe('host registration', () => {
  const PLUGIN = join(import.meta.dirname, '..');
  const REPO = join(PLUGIN, '../..');
  const readJson = (file: string) => JSON.parse(readText(file, 'utf8'));

  it('registers the Claude Code hooks from both manifests, in exec form through CLAUDE_PLUGIN_ROOT', () => {
    // Arrange
    const claudeManifest = readJson(join(PLUGIN, '.claude-plugin/plugin.json'));
    const rootManifest = readJson(join(PLUGIN, 'plugin.json'));
    const hooksPath = './com.anthropic.claude-code/hooks/hooks.json';

    // Act + Assert
    assert.equal(claudeManifest.hooks, hooksPath);
    assert.equal(rootManifest.extensions['com.anthropic.claude-code'].hooks, hooksPath);
    const hooks = readJson(join(PLUGIN, hooksPath));
    const modes: Record<string, string[]> = { PostToolUse: [], Stop: ['--reconcile'], SessionEnd: ['--session-end'] };
    assert.deepEqual(Object.keys(hooks.hooks).sort(), Object.keys(modes).sort());
    for (const [event, flags] of Object.entries(modes)) {
      for (const group of hooks.hooks[event]) {
        for (const hook of group.hooks) {
          assert.equal(hook.command, 'node');
          assert.deepEqual(hook.args, ['${CLAUDE_PLUGIN_ROOT}/scripts/telemetry/emit.mjs', ...flags]);
        }
      }
    }
    assert.equal(hooks.hooks.PostToolUse[0].hooks[0].async, true, 'post-write runs off the turn');
    assert.equal(hooks.hooks.SessionEnd[0].hooks[0].timeout, undefined, 'a plugin timeout cannot raise the SessionEnd budget');
  });

  it('wires the Cursor manifest to the Cursor hooks file and the marketplace to the plugin', () => {
    // Arrange
    const manifest = readJson(join(PLUGIN, '.cursor-plugin/plugin.json'));

    // Act + Assert
    assert.equal(manifest.hooks, '.cursor-plugin/hooks.json');
    assert.ok(existsSync(join(PLUGIN, manifest.hooks)));
    const marketplace = readJson(join(REPO, '.cursor-plugin/marketplace.json'));
    const entry = marketplace.plugins.find((p: { name: string }) => p.name === manifest.name);
    assert.ok(entry, 'the root marketplace lists this plugin');
    assert.ok(existsSync(join(REPO, entry.source, '.cursor-plugin/plugin.json')));
  });

  it('reaches the emitter through CURSOR_PLUGIN_ROOT in every Cursor hook command', () => {
    // Arrange
    const hooks = readJson(join(PLUGIN, '.cursor-plugin/hooks.json'));

    // Act + Assert
    assert.equal(hooks.version, 1);
    const modes: Record<string, string> = { afterFileEdit: '--reconcile', stop: '--reconcile', sessionEnd: '--session-end' };
    assert.deepEqual(Object.keys(hooks.hooks).sort(), Object.keys(modes).sort());
    for (const [event, flag] of Object.entries(modes)) {
      for (const hook of hooks.hooks[event]) {
        assert.equal(hook.command, `node "\${CURSOR_PLUGIN_ROOT}/scripts/telemetry/emit.mjs" ${flag}`);
      }
    }
  });
});
