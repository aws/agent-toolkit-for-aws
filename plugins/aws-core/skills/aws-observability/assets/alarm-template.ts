// Best-practice CloudWatch alarm patterns for CDK

import {
  Alarm, CompositeAlarm, AlarmRule, AlarmState,
  ComparisonOperator, MathExpression, TreatMissingData,
  Dashboard, AlarmWidget, GraphWidget, TextWidget, PeriodOverride,
} from 'aws-cdk-lib/aws-cloudwatch';
import { SnsAction } from 'aws-cdk-lib/aws-cloudwatch-actions';
import { Duration } from 'aws-cdk-lib';
import { IFunction } from 'aws-cdk-lib/aws-lambda';
import { ITopic } from 'aws-cdk-lib/aws-sns';
import { Construct } from 'constructs';

/**
 * Create Lambda monitoring with best-practice defaults.
 *
 * Best-practice defaults (vs common defaults):
 * - evaluationPeriods: 3 (not 1) — reduces false positives
 * - datapointsToAlarm: 2 (not 1) — M-of-N prevents flapping
 * - treatMissingData: NOT_BREACHING (not MISSING) — absence of errors = OK
 * - period: 60s (not 300s) — faster detection
 * - error rate uses math expression (not raw Errors count)
 * - duration uses p99 (not Average)
 */
export function createLambdaMonitoring(
  scope: Construct,
  fn: IFunction,
  snsTopic: ITopic,
  options?: {
    errorRateThreshold?: number;  // default: 5 (percent)
    durationThresholdMs?: number; // default: 3000 (ms)
  },
) {
  const errorRateThreshold = options?.errorRateThreshold ?? 5;
  const durationThreshold = options?.durationThresholdMs ?? 3000;

  // Error rate alarm (percentage via math expression)
  const errorRateAlarm = new Alarm(scope, 'ErrorRateAlarm', {
    metric: new MathExpression({
      expression: 'IF(invocations > 0, errors * 100 / invocations, 0)',
      usingMetrics: {
        errors: fn.metricErrors({ period: Duration.minutes(1) }),
        invocations: fn.metricInvocations({ period: Duration.minutes(1) }),
      },
    }),
    threshold: errorRateThreshold,
    evaluationPeriods: 3,
    datapointsToAlarm: 2,
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });

  // Duration alarm (p99, not average)
  const durationAlarm = new Alarm(scope, 'DurationP99Alarm', {
    metric: fn.metricDuration({
      statistic: 'p99',
      period: Duration.minutes(1),
    }),
    threshold: durationThreshold,
    evaluationPeriods: 3,
    datapointsToAlarm: 2,
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });

  // Throttle alarm
  const throttleAlarm = new Alarm(scope, 'ThrottleAlarm', {
    metric: fn.metricThrottles({ period: Duration.minutes(1) }),
    threshold: 1,
    evaluationPeriods: 3,
    datapointsToAlarm: 2,
    comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });

  // Composite alarm — only page when service is unhealthy
  const serviceHealthAlarm = new CompositeAlarm(scope, 'ServiceHealthAlarm', {
    alarmRule: AlarmRule.anyOf(
      AlarmRule.fromAlarm(errorRateAlarm, AlarmState.ALARM),
      AlarmRule.fromAlarm(durationAlarm, AlarmState.ALARM),
      AlarmRule.fromAlarm(throttleAlarm, AlarmState.ALARM),
    ),
  });
  serviceHealthAlarm.addAlarmAction(new SnsAction(snsTopic));

  // Dashboard
  const dashboard = new Dashboard(scope, 'ServiceDashboard', {
    start: '-PT8H',
    periodOverride: PeriodOverride.INHERIT,
  });
  dashboard.addWidgets(
    new TextWidget({ width: 24, height: 1, markdown: '# Service Health' }),
    new AlarmWidget({ width: 8, height: 6, title: 'Error Rate', alarm: errorRateAlarm }),
    new AlarmWidget({ width: 8, height: 6, title: 'Duration P99', alarm: durationAlarm }),
    new AlarmWidget({ width: 8, height: 6, title: 'Throttles', alarm: throttleAlarm }),
    new GraphWidget({
      width: 24, height: 6,
      title: 'Invocations & Errors',
      left: [fn.metricInvocations({ period: Duration.minutes(1) })],
      right: [fn.metricErrors({ period: Duration.minutes(1) })],
    }),
  );

  return { errorRateAlarm, durationAlarm, throttleAlarm, serviceHealthAlarm, dashboard };
}
