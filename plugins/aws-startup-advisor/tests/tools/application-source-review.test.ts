// Focused tests for the application-source validator. They import the production
// implementation directly and check its contract, security, filesystem behavior,
// and fail-closed behavior.
// Run: node --test plugins/aws-startup-advisor/tests/tools/application-source-review.test.ts

import assert from 'node:assert/strict';
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { describe, it } from 'node:test';
import {
  ALWAYS_QUESTIONS,
  evaluateSubmission,
  isContainedPath,
  type Json,
  type JsonObject,
  LIMITS,
  measureSourceRoot,
  object,
  QUESTIONS,
  type Question,
  retainedBytes,
  scanDisallowedContent,
  selectQuestions,
  unknownForRequest,
  validate,
  validateReviewArtifact,
  validateSemantics,
} from '../../tools/application-source-review.ts';

const pluginRoot = resolve(dirname(resolve(process.argv[1])), '../..');
const schema = JSON.parse(
  readFileSync(
    resolve(pluginRoot, 'skills/heroku-to-aws/references/shared/application-source-contract.schema.json'),
    'utf8',
  ),
) as JsonObject;

// --- fixtures -----------------------------------------------------------------

const workspaces: string[] = [];
function makeWorkspace(files: Record<string, string>): string {
  const ws = mkdtempSync(join(tmpdir(), 'asr-'));
  workspaces.push(ws);
  for (const [rel, content] of Object.entries(files)) {
    const abs = join(ws, rel);
    mkdirSync(dirname(abs), { recursive: true });
    writeFileSync(abs, content);
  }
  return ws;
}
process.on('exit', () => {
  for (const ws of workspaces) rmSync(ws, { recursive: true, force: true });
});

function context(overrides: Partial<Record<string, Json>> = {}): JsonObject {
  return {
    process_types: ['web'],
    configuration_names: ['PORT', 'SIGNING_SECRET'],
    postgres_attachment_present: false,
    redis_attachment_present: false,
    addon_ids: [],
    private_space_present: false,
    selected_estate_application_ids: [],
    ...overrides,
  };
}

function request(requested: readonly string[], ctx: JsonObject = context()): JsonObject {
  return {
    application: { app_id: 'app-primary', app_name: 'example-app' },
    requested_questions: [...requested],
    context: ctx,
  };
}

function inventory(applications = [{ app_id: 'app-primary', app_name: 'example-app' }]): JsonObject {
  return {
    apps: applications.map((application) => ({ ...application, space: null })),
    resources: [],
  };
}

const MISSING_SOURCE_DETAIL = 'Application source was not available for review.';

function publicationRequest(): JsonObject {
  return request(ALWAYS_QUESTIONS, context({
    process_types: [],
    configuration_names: [],
  }));
}

function publishableUnknown() {
  return {
    reviews: [{
      source_root: null,
      request: publicationRequest(),
      status: 'UNKNOWN',
      findings: unknownForRequest(ALWAYS_QUESTIONS, MISSING_SOURCE_DETAIL),
      limitations: [MISSING_SOURCE_DETAIL],
    }],
  };
}

function runtimeFramework(runtime: string, sources: Json[] = []): JsonObject {
  return {
    question: 'runtime_framework',
    status: 'PRESENT',
    value: [{ component_id: 'component-api', root: '.', runtime }],
    sources,
    limitations: [],
  };
}
function na(question: string): JsonObject {
  return { question, status: 'NOT_APPLICABLE', value: null, limitations: [] };
}
function findings(list: JsonObject[]): JsonObject {
  return { findings: list };
}

const NODE_SOURCES: Json[] = [{ path: 'package.json', line_start: 1, line_end: 3 }];

// --- question selection -------------------------------------------------------

describe('question selection from Heroku inventory', () => {
  it('always requests the 15 base questions in canonical order', () => {
    const selected = selectQuestions({
      hasInboundWebProcess: false,
      privateSpaceOrMultiApp: false,
      postgresAttached: false,
      redisAttached: false,
      ambiguousAddons: false,
    });
    assert.equal(ALWAYS_QUESTIONS.length, 15);
    assert.deepEqual(selected, [...ALWAYS_QUESTIONS]);
  });

  it('adds conditional questions per inventory signal, deduplicated and ordered', () => {
    const selected = selectQuestions({
      hasInboundWebProcess: true,
      privateSpaceOrMultiApp: true,
      postgresAttached: true,
      redisAttached: true,
      ambiguousAddons: true,
    });
    assert.deepEqual(selected, [...QUESTIONS]);
    for (const q of ['health_routes', 'webhooks', 'postgresql_extensions', 'redis_usage', 'addon_usage']) {
      assert.ok(selected.includes(q as Question), q);
    }
    // ordering matches the canonical question list
    assert.deepEqual(selected, QUESTIONS.filter((q) => selected.includes(q)));
  });
});

describe('schema validator object fields', () => {
  it('rejects undeclared keys inherited by ordinary JavaScript objects', () => {
    const objectSchema: JsonObject = {
      type: 'object',
      additionalProperties: false,
      properties: { runtime: { type: 'string' } },
    };
    for (const key of ['constructor', 'toString', '__proto__']) {
      const value = JSON.parse(`{"runtime":"nodejs","${key}":{"unexpected":"content"}}`) as JsonObject;
      assert.match(validate(objectSchema, value).join('\n'), new RegExp(`undeclared ${key}`));
    }
  });
});

// --- valid contracts + fail-closed replacement --------------------------------

describe('evaluateSubmission: retain vs fail closed', () => {
  for (const runtime of ['nodejs', 'ruby', 'java']) {
    it(`retains a valid ${runtime} submission whole`, () => {
      const ws = makeWorkspace({ 'package.json': '{\n  "name": "app"\n}\n' });
      const submission = findings([runtimeFramework(runtime, NODE_SOURCES)]);
      const result = evaluateSubmission({
        schema,
        request: request(['runtime_framework']),
        submission,
        roots: [ws],
        workspaceRoot: ws,
      });
      assert.deepEqual(result.reasons, []);
      assert.equal(result.retained, true);
      assert.equal(result.findings, submission);
    });
  }

  for (const runtime of ['Node.js 20', 'ruby-3.2', 'Java 21']) {
    it(`normalizes the supported runtime label ${runtime}`, () => {
      const ws = makeWorkspace({ 'package.json': '{\n  "name": "app"\n}\n' });
      const result = evaluateSubmission({
        schema,
        request: request(['runtime_framework']),
        submission: findings([runtimeFramework(runtime, NODE_SOURCES)]),
        roots: [ws],
        workspaceRoot: ws,
      });
      assert.equal(result.retained, true);
    });
  }

  it('fails an unsupported runtime closed to a valid all-UNKNOWN document', () => {
    const ws = makeWorkspace({ 'app.py': 'print("hello")\n' });
    const requested = ['runtime_framework', 'process_commands', 'network_listeners'];
    const submission = findings([
      runtimeFramework('python', [{ path: 'app.py' }]),
      na('process_commands'),
      na('network_listeners'),
    ]);
    const result = evaluateSubmission({
      schema,
      request: request(requested),
      submission,
      roots: [ws],
      workspaceRoot: ws,
    });
    assert.equal(result.retained, false);
    assert.match(result.reasons.join('\n'), /unsupported runtime: python/);
    assert.deepEqual(validate(schema, result.findings), []);
    assert.deepEqual(validateSemantics(request(requested), result.findings), []);
    for (const raw of result.findings.findings as Json[]) assert.equal(object(raw).status, 'UNKNOWN');
  });

  it('fails closed to one UNKNOWN per requested question when source is missing', () => {
    const ws = makeWorkspace({ 'package.json': '{}\n' });
    const submission = findings([runtimeFramework('nodejs', [{ path: 'does-not-exist.rb' }])]);
    const result = evaluateSubmission({
      schema,
      request: request(['runtime_framework']),
      submission,
      roots: [ws],
      workspaceRoot: ws,
    });
    assert.equal(result.retained, false);
    assert.match(result.reasons.join('\n'), /cited path does not resolve/);
    assert.equal((result.findings.findings as Json[]).length, 1);
    assert.equal(object((result.findings.findings as Json[])[0]).status, 'UNKNOWN');
  });

  it('fails closed when no source root is supplied or the source root is empty', () => {
    const submission = findings([runtimeFramework('nodejs')]);
    const ws = makeWorkspace({});
    const noRoot = evaluateSubmission({
      schema,
      request: request(['runtime_framework']),
      submission,
      roots: [],
      workspaceRoot: ws,
    });
    assert.equal(noRoot.retained, false);
    assert.match(noRoot.reasons.join('\n'), /exactly one source root/);

    const emptyRoot = evaluateSubmission({
      schema,
      request: request(['runtime_framework']),
      submission,
      roots: [ws],
      workspaceRoot: ws,
    });
    assert.equal(emptyRoot.retained, false);
    assert.match(emptyRoot.reasons.join('\n'), /no readable files/);
  });

  it('fails closed on a cited line range beyond the file', () => {
    const ws = makeWorkspace({ 'package.json': '{\n}\n' });
    const submission = findings([runtimeFramework('nodejs', [{ path: 'package.json', line_start: 3 }])]);
    const result = evaluateSubmission({
      schema,
      request: request(['runtime_framework']),
      submission,
      roots: [ws],
      workspaceRoot: ws,
    });
    assert.equal(result.retained, false);
  });

  it('resolves nested-app citations as workspace-relative paths', () => {
    const ws = makeWorkspace({ 'apps/web/package.json': '{}\n' });
    const root = resolve(ws, 'apps/web');
    const accepted = evaluateSubmission({
      schema,
      request: request(['runtime_framework']),
      submission: findings([runtimeFramework('nodejs', [{ path: 'apps/web/package.json' }])]),
      roots: [root],
      workspaceRoot: ws,
    });
    assert.equal(accepted.retained, true);

    const sourceRootRelative = evaluateSubmission({
      schema,
      request: request(['runtime_framework']),
      submission: findings([runtimeFramework('nodejs', [{ path: 'package.json' }])]),
      roots: [root],
      workspaceRoot: ws,
    });
    assert.equal(sourceRootRelative.retained, false);
  });

  it('fails closed instead of treating a request document as findings', () => {
    const ws = makeWorkspace({ 'package.json': '{}\n' });
    const reviewRequest = request(['runtime_framework']);
    const result = evaluateSubmission({
      schema,
      request: reviewRequest,
      submission: reviewRequest,
      roots: [ws],
      workspaceRoot: ws,
    });
    assert.equal(result.retained, false);
    assert.match(result.reasons.join('\n'), /findings/);
  });

  it('fails closed on malformed, duplicate, and unrequested submissions', () => {
    const ws = makeWorkspace({ 'package.json': '{\n}\n' });
    const base = { schema, roots: [ws], workspaceRoot: ws };
    // malformed: undeclared field
    const malformed = findings([{ ...runtimeFramework('nodejs'), extra: true }]);
    assert.equal(evaluateSubmission({ ...base, request: request(['runtime_framework']), submission: malformed }).retained, false);
    // duplicate finding for the same question
    const duplicate = findings([na('build_method'), na('build_method')]);
    assert.equal(evaluateSubmission({ ...base, request: request(['build_method']), submission: duplicate }).retained, false);
    // unrequested finding
    const unrequested = findings([na('process_commands')]);
    assert.equal(evaluateSubmission({ ...base, request: request(['build_method']), submission: unrequested }).retained, false);
  });

  it('fails closed without throwing on malformed wide submissions', () => {
    const ws = makeWorkspace({ 'package.json': '{}\n' });
    const malformedCases: Array<[JsonObject, JsonObject]> = [
      [
        request(['runtime_framework']),
        { findings: { unexpected: Array(130_000).fill(0) } },
      ],
      [
        request(['runtime_framework']),
        { findings: { unexpected: Array(140_000).fill(0) } },
      ],
      [
        request(['build_time_settings']),
        findings([{
          question: 'build_time_settings',
          status: 'PRESENT',
          value: Array(125_000).fill(0),
          sources: [],
          limitations: [],
        }]),
      ],
    ];
    assert.ok(retainedBytes(malformedCases[1][1]) > LIMITS.maxRetainedBytes);

    for (const [reviewRequest, submission] of malformedCases) {
      let result;
      assert.doesNotThrow(() => {
        result = evaluateSubmission({
          schema,
          request: reviewRequest,
          submission,
          roots: [ws],
          workspaceRoot: ws,
        });
      });
      assert.equal(result?.retained, false);
      assert.ok((result?.reasons.length ?? 0) <= 100);
    }
  });

  it('fails closed without throwing on deeply nested malformed submissions', () => {
    const ws = makeWorkspace({ 'package.json': '{}\n' });
    let nested: Json = 0;
    for (let depth = 0; depth < 20_000; depth += 1) nested = [nested];
    const submission = { findings: nested };
    let result;
    assert.doesNotThrow(() => {
      result = evaluateSubmission({
        schema,
        request: request(['runtime_framework']),
        submission,
        roots: [ws],
        workspaceRoot: ws,
      });
    });
    assert.equal(result?.retained, false);
    assert.ok((result?.reasons.length ?? 0) > 0);
    assert.equal(retainedBytes(submission), Number.POSITIVE_INFINITY);
  });

  it('fails closed and replaces wholesale on target-bearing output', () => {
    const ws = makeWorkspace({ 'package.json': '{\n}\n' });
    const tainted = findings([{
      question: 'process_commands',
      status: 'PRESENT',
      value: [{
        process_id: 'process-web',
        component_id: 'component-api',
        type: 'web',
        name: 'web',
        command: 'Recommend deploying on AWS Fargate',
      }],
      sources: [],
      limitations: [],
    }, runtimeFramework('nodejs')]);
    const result = evaluateSubmission({
      schema,
      request: request(['process_commands', 'runtime_framework']),
      submission: tainted,
      roots: [ws],
      workspaceRoot: ws,
    });
    assert.equal(result.retained, false);
    assert.match(result.reasons.join('\n'), /target\/architecture\/cost/);
    assert.equal((result.findings.findings as Json[]).length, 2);
    for (const raw of result.findings.findings as Json[]) assert.equal(object(raw).status, 'UNKNOWN');
  });

  it('fails closed when the retained document exceeds 256 KiB', () => {
    const ws = makeWorkspace({ 'package.json': '{\n}\n' });
    const bulky = (question: string, make: (index: number) => JsonObject): JsonObject => ({
      question,
      status: 'PRESENT',
      value: Array.from({ length: 64 }, (_unused, index) => make(index)),
      sources: [],
      limitations: [],
    });
    const text = 'x'.repeat(500);
    const nm = 'y'.repeat(128);
    const list = [
      runtimeFramework('nodejs'),
      bulky('runtime_settings', () => ({
        component_id: 'component-api',
        process_ids: [],
        setting_name: nm,
        use: text,
        required: true,
        default_present: false,
        loaded_dynamically: false,
      })),
      bulky('heroku_runtime_behavior', () => ({
        component_id: 'component-api',
        process_ids: [],
        metadata_name: nm,
        use: text,
        effect: text,
      })),
      bulky('local_file_writes', () => ({
        component_id: 'component-api',
        process_ids: [],
        read_after_write: true,
        purpose: text,
        required_lifetime: nm,
        cross_instance_required: false,
      })),
      bulky('logs_telemetry', () => ({
        component_id: 'component-api',
        process_ids: [],
        signal: 'LOG',
        destination: nm,
        setting_name: nm,
      })),
      bulky('release_setup_commands', () => ({
        component_id: 'component-api',
        command: text,
        timing: nm,
        purpose: text,
      })),
    ];
    const submission = findings(list);
    const requested = ['runtime_framework', 'runtime_settings', 'heroku_runtime_behavior', 'local_file_writes', 'logs_telemetry', 'release_setup_commands'];
    assert.ok(retainedBytes(submission) > LIMITS.maxRetainedBytes);
    assert.deepEqual(validate(schema, submission), []);
    const result = evaluateSubmission({ schema, request: request(requested), submission, roots: [ws], workspaceRoot: ws });
    assert.equal(result.retained, false);
    assert.match(result.reasons.join('\n'), /retained output/);
  });
});

// --- final artifact validation -------------------------------------------------

describe('final review artifact validation', () => {
  function retainedArtifact(reviewRequest: JsonObject, limitations: string[] = []): JsonObject {
    return {
      reviews: [{
        source_root: '.',
        request: reviewRequest,
        status: 'RETAINED',
        findings: findings([runtimeFramework('nodejs', NODE_SOURCES)]),
        limitations,
      }],
    };
  }

  it('accepts retained and canonical UNKNOWN review entries', () => {
    const ws = makeWorkspace({ 'package.json': '{\n  "name": "app"\n}\n' });
    const retainedRequest = request(['runtime_framework']);
    assert.deepEqual(validateReviewArtifact(schema, retainedArtifact(retainedRequest), ws, [retainedRequest]), []);

    const unknownRequest = publicationRequest();
    assert.deepEqual(validateReviewArtifact(schema, publishableUnknown(), ws, [unknownRequest]), []);
  });

  it('rejects altered requests, extra entry fields, and retained limitations', () => {
    const ws = makeWorkspace({ 'package.json': '{\n  "name": "app"\n}\n' });
    const retainedRequest = request(['runtime_framework']);

    const limited = validateReviewArtifact(
      schema,
      retainedArtifact(retainedRequest, ['Unexpected limitation.']),
      ws,
      [retainedRequest],
    );
    assert.match(limited.join('\n'), /RETAINED cannot have limitations/);

    const altered = retainedArtifact(request(['runtime_framework']));
    const alteredEntry = object((altered.reviews as Json[])[0]);
    const alteredRequest = object(alteredEntry.request);
    object(alteredRequest.application).app_name = 'different-app';
    assert.match(
      validateReviewArtifact(schema, altered, ws, [retainedRequest]).join('\n'),
      /request content or inventory order does not match/,
    );

    const extra = retainedArtifact(retainedRequest);
    object((extra.reviews as Json[])[0]).extra = true;
    assert.match(validateReviewArtifact(schema, extra, ws, [retainedRequest]).join('\n'), /invalid entry shape/);
  });

  it('compares request objects independent of key order but preserves array order', () => {
    const ws = makeWorkspace({ 'package.json': '{\n  "name": "app"\n}\n' });
    const expected = request(['runtime_framework']);
    const actual = {
      context: { ...object(expected.context) },
      requested_questions: [...expected.requested_questions as Json[]],
      application: {
        app_name: object(expected.application).app_name,
        app_id: object(expected.application).app_id,
      },
    };
    assert.deepEqual(validateReviewArtifact(schema, retainedArtifact(actual), ws, [expected]), []);

    const reorderedUnknown = {
      reviews: [{
        source_root: null,
        request: actual,
        status: 'UNKNOWN',
        findings: {
          findings: [{
            limitations: [{ detail: MISSING_SOURCE_DETAIL, kind: 'OTHER' }],
            sources: [],
            value: null,
            status: 'UNKNOWN',
            question: 'runtime_framework',
          }],
        },
        limitations: [MISSING_SOURCE_DETAIL],
      }],
    };
    assert.deepEqual(validateReviewArtifact(schema, reorderedUnknown, ws, [expected]), []);

    const requestedInOrder = request(['runtime_framework', 'build_method']);
    const requestedInReverse = request(['build_method', 'runtime_framework']);
    const reversedArtifact = {
      reviews: [{
        source_root: null,
        request: requestedInReverse,
        status: 'UNKNOWN',
        findings: unknownForRequest(
          requestedInReverse.requested_questions as string[],
          MISSING_SOURCE_DETAIL,
        ),
        limitations: [MISSING_SOURCE_DETAIL],
      }],
    };
    assert.match(
      validateReviewArtifact(schema, reversedArtifact, ws, [requestedInOrder]).join('\n'),
      /request content or inventory order does not match/,
    );
  });

  it('rejects malformed wide findings without throwing', () => {
    const ws = makeWorkspace({ 'package.json': '{}\n' });
    const malformedCases: Array<[JsonObject, JsonObject]> = [
      [
        request(['runtime_framework']),
        { findings: { unexpected: Array(130_000).fill(0) } },
      ],
      [
        request(['runtime_framework']),
        { findings: { unexpected: Array(140_000).fill(0) } },
      ],
      [
        request(['build_time_settings']),
        findings([{
          question: 'build_time_settings',
          status: 'PRESENT',
          value: Array(125_000).fill(0),
          sources: [],
          limitations: [],
        }]),
      ],
    ];

    for (const [reviewRequest, malformedFindings] of malformedCases) {
      const artifact = {
        reviews: [{
          source_root: '.',
          request: reviewRequest,
          status: 'RETAINED',
          findings: malformedFindings,
          limitations: [],
        }],
      };
      let errors: string[] = [];
      assert.doesNotThrow(() => {
        errors = validateReviewArtifact(schema, artifact, ws, [reviewRequest]);
      });
      assert.ok(errors.length > 0);
      assert.ok(errors.length <= 100);
    }
  });

  it('rejects deeply nested malformed findings without throwing', () => {
    const ws = makeWorkspace({ 'package.json': '{}\n' });
    const reviewRequest = request(['runtime_framework']);
    let nested: Json = 0;
    for (let depth = 0; depth < 20_000; depth += 1) nested = [nested];
    const artifact = {
      reviews: [{
        source_root: '.',
        request: reviewRequest,
        status: 'RETAINED',
        findings: { findings: nested },
        limitations: [],
      }],
    };
    let errors: string[] = [];
    assert.doesNotThrow(() => {
      errors = validateReviewArtifact(schema, artifact, ws, [reviewRequest]);
    });
    assert.ok(errors.length > 0);
  });

  it('rejects non-canonical UNKNOWN findings and wrong document types', () => {
    const ws = makeWorkspace({ 'package.json': '{}\n' });
    const unknownRequest = publicationRequest();
    const nonCanonical = publishableUnknown();
    const nonCanonicalEntry = object((nonCanonical.reviews as Json[])[0]);
    nonCanonicalEntry.findings = unknownForRequest(ALWAYS_QUESTIONS, 'Unexpected failure detail.');
    nonCanonicalEntry.limitations = ['Unexpected failure detail.'];
    assert.match(
      validateReviewArtifact(schema, nonCanonical, ws, [unknownRequest]).join('\n'),
      /canonical fail-closed replacement/,
    );

    const wrongType = retainedArtifact(request(['runtime_framework']));
    object((wrongType.reviews as Json[])[0]).findings = request(['runtime_framework']);
    assert.match(
      validateReviewArtifact(schema, wrongType, ws, [request(['runtime_framework'])]).join('\n'),
      /findings/,
    );
  });
});

// --- configuration names vs credentials ---------------------------------------

describe('configuration names vs literal credentials', () => {
  function processCommandReview(command: string): {
    artifact: JsonObject;
    reviewRequest: JsonObject;
    submission: JsonObject;
    workspace: string;
  } {
    const workspace = makeWorkspace({ 'Procfile': `web: ${command}\n` });
    const reviewRequest = request(['process_commands']);
    const submission = findings([{
      question: 'process_commands',
      status: 'PRESENT',
      value: [{
        process_id: 'process-web',
        component_id: 'component-api',
        type: 'web',
        name: 'web',
        command,
      }],
      sources: [{ path: 'Procfile', line_start: 1, line_end: 1 }],
      limitations: [],
    }]);
    return {
      workspace,
      reviewRequest,
      submission,
      artifact: {
        reviews: [{
          source_root: '.',
          request: reviewRequest,
          status: 'RETAINED',
          findings: submission,
          limitations: [],
        }],
      },
    };
  }

  function assertCommandAccepted(command: string): void {
    const review = processCommandReview(command);
    const result = evaluateSubmission({
      schema,
      request: review.reviewRequest,
      submission: review.submission,
      roots: [review.workspace],
      workspaceRoot: review.workspace,
    });
    assert.equal(result.retained, true, command);
    assert.deepEqual(
      validateReviewArtifact(
        schema,
        review.artifact,
        review.workspace,
        [review.reviewRequest],
      ),
      [],
      command,
    );
  }

  function assertCommandRejected(command: string): void {
    const review = processCommandReview(command);
    const result = evaluateSubmission({
      schema,
      request: review.reviewRequest,
      submission: review.submission,
      roots: [review.workspace],
      workspaceRoot: review.workspace,
    });
    assert.equal(result.retained, false, command);
    assert.match(result.reasons.join('\n'), /high-confidence credential/, command);
    assert.match(
      validateReviewArtifact(
        schema,
        review.artifact,
        review.workspace,
        [review.reviewRequest],
      ).join('\n'),
      /high-confidence credential/,
      command,
    );
  }

  it('allows secret-bearing configuration names without values', () => {
    for (
      const settingName of [
        'SIGNING_SECRET',
        'DATABASE_PASSWORD',
        'AWS_SECRET_ACCESS_KEY',
        '_DATABASE_PASSWORD',
        'DATABASE__PASSWORD',
        'DATABASE_PASSWORD_',
        `A${'_'.repeat(32)}PASSWORD`,
        `PASSWORD${'_'.repeat(32)}A`,
      ]
    ) {
      const clean = findings([{
        question: 'runtime_settings',
        status: 'PRESENT',
        value: [{
          component_id: 'component-api',
          process_ids: [],
          setting_name: settingName,
          use: 'credential setting name',
          required: true,
          default_present: false,
          loaded_dynamically: false,
        }],
        sources: [],
        limitations: [],
      }]);
      assert.deepEqual(scanDisallowedContent(clean), []);
    }
  });

  it('allows environment references and standard redaction placeholders in commands', () => {
    for (const command of [
      'heroku run rake seed --token=<redacted>',
      'API_KEY=******** node app.js',
      'node app.js --secret=${REDACTED}',
      'DATABASE_PASSWORD=$DATABASE_PASSWORD node app.js',
      'AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY} node app.js',
      '_DATABASE_PASSWORD=$_DATABASE_PASSWORD node app.js',
      'java -Dservice.api-key=<redacted> -jar app.jar',
      'java -Dservice.access-key=${SERVICE_ACCESS_KEY} -jar app.jar',
      `node app.js --config='{"password":"<redacted>"}'`,
      `node app.js --config='{"token":"\${SERVICE_TOKEN}"}'`,
    ]) {
      const clean = findings([{
        question: 'process_commands',
        status: 'PRESENT',
        value: [{ process_id: 'p', component_id: 'c', type: 'web', name: 'web', command }],
        sources: [],
        limitations: [],
      }]);
      assert.deepEqual(validate(schema, clean), []);
      assert.deepEqual(scanDisallowedContent(clean), []);
    }
  });

  it('accepts lowercase environment references and redacted camelCase credentials', () => {
    for (const command of [
      'DATABASE_PASSWORD=${database_password} node app.js',
      'DATABASE_PASSWORD=$database_password node app.js',
      'node app.js --password=${database_password}',
      `node app.js --config='{"clientSecret":"<redacted>"}'`,
      'java -Dservice.clientSecret=${client_secret} -jar app.jar',
      'java -Dpassword=${database_password} -jar app.jar',
      'java -Dserver.port=5000 -jar app.jar',
    ]) assertCommandAccepted(command);
  });

  it('accepts Bearer authentication as a description at both validation boundaries', () => {
    const ws = makeWorkspace({ 'config/auth.json': '{}\n' });
    const reviewRequest = request(['external_services']);
    const submission = findings([{
      question: 'external_services',
      status: 'PRESENT',
      value: [{
        dependency_id: 'external-api',
        component_id: 'component-api',
        process_ids: [],
        direction: 'OUTBOUND',
        category: 'API',
        service_reference: 'Example API',
        setting_name: 'EXAMPLE_API_URL',
        role: 'reads customer records',
        protocol: 'https',
        authentication_mechanism: 'Bearer authentication',
        allowlist_behavior: 'unknown',
      }],
      sources: [{ path: 'config/auth.json', line_start: 1, line_end: 1 }],
      limitations: [],
    }]);
    const result = evaluateSubmission({
      schema,
      request: reviewRequest,
      submission,
      roots: [ws],
      workspaceRoot: ws,
    });
    assert.equal(result.retained, true);
    assert.deepEqual(validateReviewArtifact(schema, {
      reviews: [{
        source_root: '.',
        request: reviewRequest,
        status: 'RETAINED',
        findings: submission,
        limitations: [],
      }],
    }, ws, [reviewRequest]), []);
  });

  it('rejects a high-confidence literal credential', () => {
    const leaked = findings([{
      question: 'process_commands',
      status: 'PRESENT',
      value: [{ process_id: 'p', component_id: 'c', type: 'web', name: 'web', command: 'AKIAIOSFODNN7EXAMPLE deploy' }],
      sources: [],
      limitations: [],
    }]);
    assert.ok(scanDisallowedContent(leaked).length > 0);
  });

  it('rejects literal assignments to prefixed secret-bearing configuration names', () => {
    const bearerHeader = ['Author', 'ization: Bearer '].join('');
    for (const command of [
      'DATABASE_PASSWORD=syntheticExampleValue123 node app.js',
      'AWS_SECRET_ACCESS_KEY=syntheticExampleValue123 node app.js',
      '_DATABASE_PASSWORD=syntheticExampleValue123 node app.js',
      'DATABASE__PASSWORD=syntheticExampleValue123 node app.js',
      'DATABASE_PASSWORD_=syntheticExampleValue123 node app.js',
      'java -Dservice.api-key=syntheticVerifyValue123 -jar app.jar',
      'java -Dservice.access-key=syntheticVerifyValue123 -jar app.jar',
      `node app.js --config='{"password":"syntheticVerifyValue123"}'`,
      `node app.js --config='{"token":"syntheticVerifyValue123"}'`,
      'JAVA_TOOL_OPTIONS=-Dservice.password=syntheticExample123',
      'JAVA_TOOL_OPTIONS="-Dservice.password=syntheticExample123"',
      'OPT=value1234;DATABASE_PASSWORD=syntheticExample123',
      'DATABASE_PASSWORD=abc1234',
      'node app.js --password=abc1234',
      `node app.js --config='{"password":"abc1234"}'`,
      `node app.js --config='{"clientSecret":"SyntheticReviewOnly987654"}'`,
      'java -Dservice.clientSecret=SyntheticReviewOnly987654 -jar app.jar',
      'java -Dpassword=SyntheticProbeOnly123 -jar app.jar',
      'java -Dtoken=SyntheticProbeOnly123 -jar app.jar',
      'java -Dsecret=SyntheticProbeOnly123 -jar app.jar',
      `curl -H "${bearerHeader}syntheticTokenValue123" https://example.test`,
      `curl -H "${bearerHeader}syntheticTokenValue" https://example.test`,
      'run "(Bearer SyntheticReviewOnly987654)"',
      'run "Bearer SyntheticReviewOnly987654:"',
    ]) {
      assertCommandRejected(command);
    }
  });

  it('handles underscore-heavy configuration names without excessive backtracking', () => {
    const ws = makeWorkspace({ 'package.json': '{\n  "name": "app"\n}\n' });
    const reviewRequest = request(['runtime_framework'], context({
      configuration_names: [
        `A${'_'.repeat(32)}PASSWORD`,
        `PASSWORD${'_'.repeat(32)}A`,
      ],
    }));
    const submission = findings([runtimeFramework('nodejs', NODE_SOURCES)]);

    const started = Date.now();
    const result = evaluateSubmission({
      schema,
      request: reviewRequest,
      submission,
      roots: [ws],
      workspaceRoot: ws,
    });
    assert.equal(result.retained, true);
    assert.deepEqual(
      validateReviewArtifact(schema, {
        reviews: [{
          source_root: '.',
          request: reviewRequest,
          status: 'RETAINED',
          findings: submission,
          limitations: [],
        }],
      }, ws, [reviewRequest]),
      [],
    );
    assert.ok(Date.now() - started < 1000, 'credential validation exceeded one second');
  });

  it('rejects connection strings and bearer tokens', () => {
    const leaked = findings([{
      question: 'process_commands',
      status: 'PRESENT',
      value: [{
        process_id: 'p',
        component_id: 'c',
        type: 'web',
        name: 'web',
        command: 'run --database postgres://admin:supersensitive@db.example/app',
      }],
      sources: [],
      limitations: [],
    }]);
    assert.ok(scanDisallowedContent(leaked).length > 0);
  });

  it('allows source identifiers containing architecture or recommendation', () => {
    const clean = findings([{
      question: 'process_commands',
      status: 'PRESENT',
      value: [{
        process_id: 'p',
        component_id: 'c',
        type: 'worker',
        name: 'recommendation-engine',
        command: 'node recommendation-engine.js --architecture arm64',
      }],
      sources: [],
      limitations: [],
    }]);
    assert.deepEqual(scanDisallowedContent(clean), []);
  });

  it('allows an existing AWS dependency without treating it as a target recommendation', () => {
    const dependency = findings([{
      question: 'external_services',
      status: 'PRESENT',
      value: [{
        dependency_id: 'database',
        component_id: 'component-api',
        process_ids: ['process-web'],
        direction: 'OUTBOUND',
        category: 'DATABASE',
        service_reference: 'Amazon RDS',
        setting_name: 'DATABASE_URL',
        role: 'deployment reads the existing Amazon RDS reporting replica',
        protocol: 'postgresql',
        authentication_mechanism: 'connection string setting',
        allowlist_behavior: 'unknown',
      }],
      sources: [],
      limitations: [],
    }]);
    const recurringJob = findings([{
      question: 'recurring_jobs',
      status: 'PRESENT',
      value: [{
        job_id: 'nightly-totals',
        component_id: 'component-api',
        process_ids: ['process-worker'],
        name: 'nightly totals',
        mechanism: 'scheduler',
        command: 'bin/totals',
        coordination: 'existing nightly migration of totals into Amazon Aurora',
      }],
      sources: [],
      limitations: [],
    }]);
    const positionalParameter = findings([{
      question: 'process_commands',
      status: 'PRESENT',
      value: [{
        process_id: 'process-web',
        component_id: 'component-api',
        type: 'web',
        name: 'web',
        command: 'bin/start $1',
      }],
      sources: [],
      limitations: [],
    }]);
    for (const clean of [dependency, recurringJob, positionalParameter]) {
      assert.deepEqual(validate(schema, clean), []);
      assert.deepEqual(scanDisallowedContent(clean), []);
    }
  });

  it('still rejects explicit target recommendations and cost estimates', () => {
    for (const command of ['Recommend deploying on AWS Fargate', 'Estimated at $120/month']) {
      const tainted = findings([{
        question: 'process_commands',
        status: 'PRESENT',
        value: [{ process_id: 'p', component_id: 'c', type: 'web', name: 'web', command }],
        sources: [],
        limitations: [],
      }]);
      assert.ok(scanDisallowedContent(tainted).length > 0);
    }
  });
});

// --- containment --------------------------------------------------------------

describe('path containment', () => {
  it('rejects lexically unsafe cited paths at the schema layer', () => {
    for (const path of ['/etc/passwd', 'C:/secret', '../secret', 'src/../secret', 'src//x', String.raw`src\secret`]) {
      const doc = findings([{ ...runtimeFramework('nodejs'), sources: [{ path }] }]);
      assert.ok(validate(schema, doc).length > 0, path);
    }
  });

  it('contains real paths and rejects symlinks that escape the workspace', () => {
    const outside = makeWorkspace({ 'secret.txt': 'top secret\n' });
    const ws = makeWorkspace({ 'app.rb': 'puts 1\n' });
    symlinkSync(outside, join(ws, 'escape'));
    assert.equal(isContainedPath(ws, join(ws, 'app.rb')), true);
    assert.equal(isContainedPath(ws, join(ws, 'escape')), false);

    const submission = findings([na('runtime_framework')]);
    const result = evaluateSubmission({
      schema,
      request: request(['runtime_framework']),
      submission,
      roots: [join(ws, 'escape')],
      workspaceRoot: ws,
    });
    assert.equal(result.retained, false);
    assert.match(result.reasons.join('\n'), /source root escapes workspace/);
  });

  it('measures source while excluding generated, dependency, and state directories', () => {
    const ws = makeWorkspace({
      'a.js': 'a\n',
      'lib/b.js': 'b\n',
      '.git/objects/data': 'ignored\n',
      '.gradle/cache/data': 'ignored\n',
      '.next/cache/data': 'ignored\n',
      'coverage/report.json': 'ignored\n',
      'dist/app.js': 'ignored\n',
      'target/classes/App.class': 'ignored\n',
      'vendor/bundle/gem.rb': 'ignored\n',
    });
    const measured = measureSourceRoot(ws);
    assert.equal(measured.files, 2);
    assert.equal(measured.unreadableEntries, 0);
    assert.ok(measured.withinLimits);
    assert.ok(measured.totalBytes <= LIMITS.maxTotalBytes);
  });

  it('counts and accepts source files whose names match excluded directories', () => {
    const ws = makeWorkspace({
      'package.json': '{}\n',
      'bin/build': '#!/bin/sh\nnpm run build\n',
      'build/generated.js': 'ignored\n',
    });
    const measured = measureSourceRoot(ws);
    assert.equal(measured.files, 2);

    const reviewRequest = request(['build_method']);
    const submission = findings([{
      question: 'build_method',
      status: 'PRESENT',
      value: [{
        component_id: 'component-api',
        method: 'script',
        authority_path: 'bin/build',
      }],
      sources: [{ path: 'bin/build' }],
      limitations: [],
    }]);
    const result = evaluateSubmission({
      schema,
      request: reviewRequest,
      submission,
      roots: [ws],
      workspaceRoot: ws,
    });
    assert.equal(result.retained, true);

    const artifact = {
      reviews: [{
        source_root: '.',
        request: reviewRequest,
        status: 'RETAINED',
        findings: submission,
        limitations: [],
      }],
    };
    assert.deepEqual(validateReviewArtifact(schema, artifact, ws, [reviewRequest]), []);
  });

  it('rejects source roots nested inside excluded directories', () => {
    for (const sourceRoot of ['.migration/previous-run', '.git/cache', 'node_modules/dependency']) {
      const sourcePath = `${sourceRoot}/package.json`;
      const ws = makeWorkspace({ [sourcePath]: '{}\n' });
      const reviewRequest = request(['runtime_framework']);
      const submission = findings([runtimeFramework('nodejs', [{ path: sourcePath }])]);
      const result = evaluateSubmission({
        schema,
        request: reviewRequest,
        submission,
        roots: [resolve(ws, sourceRoot)],
        workspaceRoot: ws,
      });
      assert.equal(result.retained, false);
      assert.match(result.reasons.join('\n'), /source root uses an excluded directory/);

      const artifact = {
        reviews: [{
          source_root: sourceRoot,
          request: reviewRequest,
          status: 'RETAINED',
          findings: submission,
          limitations: [],
        }],
      };
      assert.match(
        validateReviewArtifact(schema, artifact, ws, [reviewRequest]).join('\n'),
        /source root uses an excluded directory/,
      );
    }
  });

  it('fails closed for unreadable citations with and without line bounds', () => {
    const ws = makeWorkspace({ 'app.js': 'console.log("hello");\n' });
    const citedFile = resolve(ws, 'app.js');
    chmodSync(citedFile, 0o000);
    try {
      const sources: JsonObject[] = [{ path: 'app.js' }, { path: 'app.js', line_start: 1 }];
      for (const source of sources) {
        const result = evaluateSubmission({
          schema,
          request: request(['runtime_framework']),
          submission: findings([runtimeFramework('nodejs', [source])]),
          roots: [ws],
          workspaceRoot: ws,
        });
        assert.equal(result.retained, false);
        assert.match(result.reasons.join('\n'), /cited path does not resolve/);
      }
    } finally {
      chmodSync(citedFile, 0o600);
    }
  });

  it('skips internal symlinks and rejects symlink or migration-state citations', () => {
    const outside = makeWorkspace({ 'secret.txt': 'not reviewed\n' });
    const ws = makeWorkspace({
      'package.json': '{}\n',
      '.migration/0901/application-source-review.json': '{}\n',
      'dist/generated.js': 'generated\n',
    });
    symlinkSync(resolve(outside, 'secret.txt'), resolve(ws, 'linked-secret.txt'));
    const measured = measureSourceRoot(ws);
    assert.equal(measured.files, 1);
    assert.equal(measured.unreadableEntries, 0);

    for (const path of ['linked-secret.txt', '.migration/0901/application-source-review.json', 'dist/generated.js']) {
      const result = evaluateSubmission({
        schema,
        request: request(['runtime_framework']),
        submission: findings([runtimeFramework('nodejs', [{ path }])]),
        roots: [ws],
        workspaceRoot: ws,
      });
      assert.equal(result.retained, false);
      assert.match(result.reasons.join('\n'), /cited path does not resolve/);
    }
  });
});
