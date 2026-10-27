// Contract tests import the production validator (tools/application-source-review.ts)
// so these checks will also apply when a later source-review phase invokes it.
// Run: node --test plugins/aws-startup-advisor/tests/tools/application-source-contract.test.ts

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { describe, it } from 'node:test';
import {
  type Json,
  type JsonObject,
  object,
  QUESTIONS,
  type Question,
  validate,
  validateSemantics,
} from '../../tools/application-source-review.ts';

const pluginRoot = resolve(dirname(resolve(process.argv[1])), '../..');
const schemaPath = resolve(
  pluginRoot,
  'skills/heroku-to-aws/references/shared/application-source-contract.schema.json',
);
const schema = JSON.parse(readFileSync(schemaPath, 'utf8')) as JsonObject;

function assertJsonEqual(actual: Json, expected: Json): void {
  assert.equal(JSON.stringify(actual), JSON.stringify(expected));
}

function request(selected: readonly string[] = QUESTIONS): JsonObject {
  return {
    application: { app_id: 'app-primary', app_name: 'example-app' },
    requested_questions: [...selected],
    context: {
      process_types: ['web'],
      configuration_names: ['API_URL', 'DATABASE_URL', 'PORT', 'REDIS_URL', 'SIGNING_SECRET'],
      postgres_attachment_present: true,
      redis_attachment_present: true,
      addon_ids: ['addon-postgres'],
      private_space_present: true,
      selected_estate_application_ids: ['app-secondary'],
    },
  };
}

const values: Record<Question, Json[]> = {
  runtime_framework: [{ component_id: 'component-api', root: '.', runtime: 'nodejs', runtime_version: '24', framework: 'express' }],
  build_method: [{ component_id: 'component-api', method: 'buildpack', authority_path: 'package.json', context_path: 'services/api' }],
  build_time_settings: [{ component_id: 'component-api', setting_name: 'API_URL', stage: 'build', required: true }],
  process_commands: [{
    process_id: 'process-web',
    component_id: 'component-api',
    type: 'web',
    name: 'web',
    command: 'node server.js',
    entrypoint: 'server.js',
  }],
  runtime_settings: [{
    component_id: 'component-api',
    process_ids: ['process-web'],
    setting_name: 'PORT',
    use: 'HTTP listener port',
    required: true,
    default_present: false,
    loaded_dynamically: false,
  }],
  network_listeners: [{
    listener_id: 'listener-http',
    component_id: 'component-api',
    process_id: 'process-web',
    transport: 'TCP',
    port_setting_name: 'PORT',
    default_port: 3000,
    intended_traffic: 'public',
  }],
  port_host_binding: [{
    listener_id: 'listener-http',
    host_setting_name: 'HOST',
    port_setting_name: 'PORT',
    fixed_host: '0.0.0.0',
    fixed_port: 3000,
    host_configurable: true,
    port_configurable: true,
    beyond_loopback: true,
  }],
  heroku_runtime_behavior: [{
    component_id: 'component-api',
    process_ids: ['process-web'],
    metadata_name: 'DYNO',
    use: 'Instance labeling',
    effect: 'Changes log labels',
  }],
  native_dependencies: [{
    component_id: 'component-api',
    kind: 'library',
    name: 'libvips',
    phase: 'runtime',
    process_ids: ['process-web'],
    os_constraints: ['linux'],
    architecture_constraints: ['amd64'],
  }],
  release_setup_commands: [{
    component_id: 'component-api',
    process_id: 'process-web',
    command: 'npm run migrate',
    timing: 'release',
    purpose: 'Apply database migrations',
  }],
  recurring_jobs: [{
    job_id: 'job-cleanup',
    component_id: 'component-api',
    process_ids: ['process-web'],
    name: 'cleanup',
    mechanism: 'scheduler',
    command: 'npm run cleanup',
    schedule: '0 2 * * *',
    coordination: 'single execution',
  }],
  health_routes: [{
    component_id: 'component-api',
    process_id: 'process-web',
    listener_id: 'listener-http',
    path: '/health',
    methods: ['GET'],
    success_statuses: [200],
    redirects: false,
    authentication: 'none',
    required_headers: [],
  }],
  local_file_writes: [{
    component_id: 'component-api',
    process_ids: ['process-web'],
    setting_name: 'UPLOAD_DIR',
    default_path: 'tmp/uploads',
    read_after_write: true,
    purpose: 'Temporary upload processing',
    required_lifetime: 'request',
    cross_instance_required: false,
  }],
  network_protocols: [{
    component_id: 'component-api',
    process_ids: ['process-web'],
    direction: 'INBOUND',
    listener_id: 'listener-http',
    transport: 'TCP',
    application_protocol: 'HTTP',
    port: 3000,
    application_managed_tls: false,
  }],
  potential_private_endpoints: [{
    component_id: 'component-api',
    process_ids: ['process-web'],
    reference_kind: 'DEPENDENCY',
    reference_id: 'dependency-payments',
    setting_name: 'API_URL',
    host_pattern: 'internal.example.com',
    protocol: 'HTTPS',
    port: 443,
  }],
  logs_telemetry: [{
    component_id: 'component-api',
    process_ids: ['process-web'],
    signal: 'LOG',
    destination: 'stdout',
    setting_name: 'LOG_LEVEL',
    file_path: 'logs/application.log',
  }],
  postgresql_extensions: [{
    component_id: 'component-api',
    database_setting_name: 'DATABASE_URL',
    extension: 'pg_trgm',
    declaration_kind: 'migration',
    action: 'verify compatibility',
  }],
  redis_usage: [{
    component_id: 'component-api',
    setting_name: 'REDIS_URL',
    roles: ['cache'],
    disposability: 'DISPOSABLE',
  }],
  external_services: [{
    dependency_id: 'dependency-payments',
    component_id: 'component-api',
    process_ids: ['process-web'],
    direction: 'OUTBOUND',
    category: 'payments',
    service_reference: 'payment-api',
    setting_name: 'API_URL',
    role: 'Create charges',
    protocol: 'HTTPS',
    port: 443,
    authentication_mechanism: 'bearer token',
    allowlist_behavior: 'fixed egress required',
  }],
  application_connections: [{
    relationship_id: 'relationship-worker',
    caller_component_id: 'component-api',
    caller_process_ids: ['process-web'],
    callee_application_id: 'app-secondary',
    setting_name: 'WORKER_URL',
    protocol: 'HTTPS',
    ports: [443],
    mechanism: 'HTTP API',
  }],
  addon_usage: [{
    inventory_addon_id: 'addon-postgres',
    component_id: 'component-api',
    setting_name: 'DATABASE_URL',
    usage: 'RETAINED_EXTERNAL',
    roles: ['primary database'],
  }],
  webhooks: [{
    component_id: 'component-api',
    process_id: 'process-web',
    listener_id: 'listener-http',
    path: '/webhooks/payments',
    methods: ['POST'],
    provider_reference: 'payment provider',
    verification_mechanism: 'HMAC',
    verification_setting_name: 'SIGNING_SECRET',
    required_headers: ['X-Signature'],
  }],
};

function presentFindings(selected: readonly Question[] = QUESTIONS): JsonObject {
  return {
    findings: selected.map((question, index) => ({
      question,
      status: 'PRESENT',
      value: values[question],
      sources: index === 0
        ? [{ path: 'package.json', line_start: 1, line_end: 8 }]
        : [{ path: 'package.json' }],
      limitations: [],
    })),
  };
}

function clone<T extends Json>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

describe('application-source contract', () => {
  it('declares all approved questions', () => {
    assertJsonEqual(object(object(schema.definitions).question).enum, [...QUESTIONS]);
  });

  it('accepts a request and resolvable PRESENT findings covering all questions', () => {
    const reviewRequest = request();
    const answer = presentFindings();
    assertJsonEqual(validate(schema, reviewRequest), []);
    assertJsonEqual(validate(schema, answer), []);
    assertJsonEqual(validateSemantics(reviewRequest, answer), []);
  });

  it('accepts bounded non-present statuses and requires a limitation for UNKNOWN', () => {
    const reviewRequest = request(['runtime_framework', 'build_method', 'build_time_settings']);
    const answer: JsonObject = {
      findings: [
        {
          question: 'runtime_framework',
          status: 'ABSENT_WITHIN_REVIEWED_SCOPE',
          value: null,
          sources: [{ path: 'package.json' }],
          limitations: [],
        },
        {
          question: 'build_method',
          status: 'UNKNOWN',
          value: null,
          limitations: [{ kind: 'UNREADABLE_SOURCE', detail: 'Build manifest could not be read.' }],
        },
        { question: 'build_time_settings', status: 'NOT_APPLICABLE', value: null, limitations: [] },
      ],
    };
    assertJsonEqual(validate(schema, answer), []);
    assertJsonEqual(validateSemantics(reviewRequest, answer), []);
    object((answer.findings as Json[])[0]).sources = [];
    assert.match(validateSemantics(reviewRequest, answer).join('\n'), /needs source evidence/);
    object((answer.findings as Json[])[0]).sources = [{ path: 'package.json' }];
    (object((answer.findings as Json[])[1]).limitations as Json[]) = [];
    assert.ok(validate(schema, answer).length > 0);
    assert.match(validateSemantics(reviewRequest, answer).join('\n'), /UNKNOWN needs a limitation/);
  });

  it('does not throw when malformed findings omit limitations', () => {
    for (const status of ['UNKNOWN', 'ABSENT_WITHIN_REVIEWED_SCOPE'] as const) {
      const reviewRequest = request(['runtime_framework']);
      const answer = presentFindings(['runtime_framework']);
      const finding = object((answer.findings as Json[])[0]);
      finding.status = status;
      finding.value = null;
      delete finding.limitations;

      assert.ok(validate(schema, answer).length > 0);
      const errors = validateSemantics(reviewRequest, answer);
      if (status === 'UNKNOWN') assert.match(errors.join('\n'), /UNKNOWN needs a limitation/);
    }
  });

  it('rejects undeclared, value-bearing, malformed, and unbounded request data', () => {
    for (const mutate of [
      (sample: JsonObject) => sample.secret = 'no',
      (sample: JsonObject) => object(sample.context).configuration_values = { API_URL: 'secret' },
      (sample: JsonObject) => object(sample.context).credentials = ['token'],
      (sample: JsonObject) => object(sample.application).app_name = '',
      (sample: JsonObject) => object(sample.application).app_name = 'x'.repeat(129),
      (sample: JsonObject) => (sample.requested_questions as Json[]).push('runtime_framework'),
      (sample: JsonObject) => (sample.requested_questions as Json[])[0] = 'not_a_question',
    ]) {
      const sample = request();
      mutate(sample);
      assert.ok(validate(schema, sample).length > 0);
    }
  });

  it('accepts up to 256 configuration names and records per question', () => {
    const reviewRequest = request(['runtime_settings']);
    object(reviewRequest.context).configuration_names = Array.from(
      { length: 256 },
      (_, index) => `SETTING_${index}`,
    );
    assertJsonEqual(validate(schema, reviewRequest), []);
    (object(reviewRequest.context).configuration_names as Json[]).push('SETTING_256');
    assert.ok(validate(schema, reviewRequest).length > 0);

    const answer = presentFindings(['runtime_settings']);
    const finding = object((answer.findings as Json[])[0]);
    finding.value = Array.from(
      { length: 256 },
      (_, index) => ({ ...object(values.runtime_settings[0]), setting_name: `SETTING_${index}` }),
    );
    assertJsonEqual(validate(schema, answer), []);
    (finding.value as Json[]).push({ ...object(values.runtime_settings[0]), setting_name: 'SETTING_256' });
    assert.ok(validate(schema, answer).length > 0);
  });

  it('rejects malformed findings, values, and source locations', () => {
    const base = presentFindings(['network_listeners']);
    const finding = () => object((clone(base).findings as Json[])[0]);
    for (const sample of [
      Object.assign(finding(), { extra: true }),
      Object.assign(finding(), { status: 'MAYBE' }),
      Object.assign(finding(), { value: null }),
      Object.assign(finding(), { status: 'NOT_APPLICABLE' }),
      Object.assign(finding(), { limitations: [{ kind: 'OTHER', detail: '' }] }),
      Object.assign(finding(), {
        value: [{ ...object(values.network_listeners[0]), default_port: 70000 }],
      }),
    ]) {
      assert.ok(validate(schema, { findings: [sample] }).length > 0);
    }
    for (
      const path of [
        '/etc/passwd',
        'C:/secret',
        'C:secret',
        '.',
        'src/./secret',
        '..',
        '../secret',
        'src/../secret',
        'src//secret',
        String.raw`src\secret`,
        ' /etc/passwd',
        '\t/etc/passwd',
        ' ..',
        ' ./secret',
        ' C:/secret',
        'src/ ../secret',
        '~/.ssh/id_rsa',
        'src/file.js ',
      ]
    ) {
      const sample = finding();
      sample.sources = [{ path }];
      assert.ok(validate(schema, { findings: [sample] }).length > 0, path);
    }
    const pathWithInternalSpace = finding();
    pathWithInternalSpace.sources = [{ path: 'src/My File.js' }];
    assertJsonEqual(validate(schema, { findings: [pathWithInternalSpace] }), []);
  });

  it('rejects duplicate, missing, and unrequested findings', () => {
    const reviewRequest = request(['runtime_framework']);
    const answer = presentFindings(['runtime_framework']);
    (answer.findings as Json[]).push(clone((answer.findings as Json[])[0]));
    assert.match(validateSemantics(reviewRequest, answer).join('\n'), /expected one finding/);
    (answer.findings as Json[]) = [];
    assert.match(validateSemantics(reviewRequest, answer).join('\n'), /expected one finding/);
    const unrequested = presentFindings(['build_method']);
    assert.match(validateSemantics(reviewRequest, unrequested).join('\n'), /unrequested finding/);

    const duplicateId = presentFindings();
    const runtimeValue = object((duplicateId.findings as Json[])[0]).value as Json[];
    runtimeValue.push(clone(runtimeValue[0]));
    assert.match(validateSemantics(request(), duplicateId).join('\n'), /duplicate component id/);
  });

  it('accepts partial requests when the defining question was not requested', () => {
    for (const question of [
      'process_commands',
      'network_listeners',
      'health_routes',
      'potential_private_endpoints',
    ] as const) {
      const reviewRequest = request([question]);
      const answer = presentFindings([question]);
      assertJsonEqual(validate(schema, answer), []);
      assertJsonEqual(validateSemantics(reviewRequest, answer), []);
    }
  });

  it('accepts references when the requested defining finding is not PRESENT', () => {
    for (const [definingQuestion, referencingQuestion] of [
      ['runtime_framework', 'process_commands'],
      ['process_commands', 'network_listeners'],
      ['network_listeners', 'health_routes'],
      ['external_services', 'potential_private_endpoints'],
    ] as const) {
      const reviewRequest = request([definingQuestion, referencingQuestion]);
      const answer = presentFindings([referencingQuestion]);
      (answer.findings as Json[]).unshift({
        question: definingQuestion,
        status: 'UNKNOWN',
        value: null,
        limitations: [{ kind: 'OTHER', detail: 'Source did not establish this answer.' }],
      });

      assertJsonEqual(validate(schema, answer), []);
      assertJsonEqual(validateSemantics(reviewRequest, answer), []);
    }
  });

  it('retains source names that are absent from Heroku inventory context', () => {
    const selected = [
      'process_commands',
      'port_host_binding',
      'logs_telemetry',
      'local_file_writes',
      'application_connections',
    ] as const;
    const reviewRequest = request(selected);
    const answer = presentFindings(selected);
    const processFinding = (answer.findings as Json[]).map(object).find((item) =>
      item.question === 'process_commands'
    );
    if (!processFinding || !Array.isArray(processFinding.value)) throw new Error('missing process_commands');
    object(processFinding.value[0]).type = 'worker';

    assertJsonEqual(validate(schema, answer), []);
    assertJsonEqual(validateSemantics(reviewRequest, answer), []);
  });

  it('rejects qualified absence and reversed line bounds', () => {
    const reviewRequest = request(['runtime_framework']);
    const answer: JsonObject = {
      findings: [{
        question: 'runtime_framework',
        status: 'ABSENT_WITHIN_REVIEWED_SCOPE',
        value: null,
        sources: [{ path: 'package.json', line_start: 8, line_end: 1 }],
        limitations: [{ kind: 'TRUNCATED_SOURCE', detail: 'The manifest exceeded the review limit.' }],
      }],
    };
    assert.match(validateSemantics(reviewRequest, answer).join('\n'), /incomplete scope/);
    assert.match(validateSemantics(reviewRequest, answer).join('\n'), /line bounds are reversed/);
  });

  it('rejects broken shared references', () => {
    for (const [question, key] of [
      ['build_method', 'component_id'],
      ['network_listeners', 'process_id'],
      ['health_routes', 'listener_id'],
      ['potential_private_endpoints', 'reference_id'],
      ['application_connections', 'callee_application_id'],
      ['addon_usage', 'inventory_addon_id'],
    ] as const) {
      const answer = presentFindings();
      const finding = (answer.findings as Json[]).map(object).find((item) => item.question === question);
      if (!finding || !Array.isArray(finding.value)) throw new Error(`missing value for ${question}`);
      object(finding.value[0])[key] = 'missing-id';
      assert.ok(validateSemantics(request(), answer).length > 0, `${question}.${key}`);
    }
  });
});
