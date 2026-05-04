# Advanced Features

## Geo (Location) — Backend + Frontend

Add map display and location search using CDK constructs in
`amplify/backend.ts`:

```typescript
import { defineBackend } from '@aws-amplify/backend';
import * as geo from 'aws-cdk-lib/aws-location';

const backend = defineBackend({ auth });
const geoStack = backend.createStack('GeoStack');

const placeIndex = new geo.CfnPlaceIndex(geoStack, 'PlaceIndex', {
  dataSource: 'Esri',
  indexName: 'myPlaceIndex',
});

const map = new geo.CfnMap(geoStack, 'Map', {
  mapName: 'myMap',
  configuration: { style: 'VectorEsriNavigation' },
});

backend.addOutput({
  geo: {
    aws_region: geoStack.region,
    maps: { items: { [map.mapName]: { style: 'VectorEsriNavigation' } } },
    search_indices: { items: [placeIndex.indexName] },
  },
});
```

Grant authenticated users access via IAM policy on the geo resources.

**Frontend:** Install `@aws-amplify/geo` and `maplibre-gl-js-amplify`.
Use `Amplify.Geo.searchByText()` for search and `AmplifyMapLibreRequest`
for rendering maps. See
[AWS Amplify Geo docs](https://docs.amplify.aws/react/build-a-backend/add-aws-services/geo/)
for full client setup.

## PubSub — Backend + Frontend

Real-time messaging via AWS IoT Core. Configure an IoT endpoint and
attach an IAM policy for authenticated users in `amplify/backend.ts`:

```typescript
import * as iam from 'aws-cdk-lib/aws-iam';

const pubsubStack = backend.createStack('PubSubStack');

backend.auth.resources.authenticatedUserIamRole.addToPrincipalPolicy(
  new iam.PolicyStatement({
    actions: ['iot:Connect', 'iot:Publish', 'iot:Subscribe', 'iot:Receive'],
    resources: [
      `arn:aws:iot:*:*:client/\${cognito-identity.amazonaws.com:sub}`,
      `arn:aws:iot:*:*:topic/amplify/*`,
      `arn:aws:iot:*:*:topicfilter/amplify/*`,
    ],
  })
);

backend.addOutput({
  custom: { iotEndpoint: 'your-iot-endpoint.iot.region.amazonaws.com' },
});
```

**Frontend** — subscribe and publish:

```typescript
import { PubSub } from '@aws-amplify/pubsub';

const sub = PubSub.subscribe({ topics: ['myTopic'] }).subscribe({
  next: (data) => console.log('Message:', data),
  error: (err) => console.error(err),
});

await PubSub.publish({ topics: ['myTopic'], message: { msg: 'hello' } });
sub.unsubscribe();  // MUST unsubscribe to prevent leaks
```

When using subscriptions in React, **MUST** wrap in `useEffect` and return
cleanup function to call `.unsubscribe()`.

Retrieve the IoT endpoint programmatically:
`aws iot describe-endpoint --endpoint-type iot:Data-ATS`.
See [AWS Amplify PubSub docs](https://docs.amplify.aws/react/build-a-backend/add-aws-services/pubsub/)
for connection configuration.

## Custom CDK Stacks — Backend Only

Create additional CloudFormation stacks for resources not natively
supported by Amplify:

```typescript
const backend = defineBackend({ auth, data });
const customStack = backend.createStack('AnalyticsStack');

// Use any CDK construct in the custom stack
import * as sns from 'aws-cdk-lib/aws-sns';
const topic = new sns.Topic(customStack, 'NotificationTopic');

// Access Amplify resources from custom stack
const userPool = backend.auth.resources.userPool;
```

Stack names **MUST** be unique within the backend — duplicate names cause
deployment failures. Use descriptive names like `'EmailStack'`,
`'AnalyticsStack'`.

## Backend Overrides — Backend Only

Access and modify underlying CloudFormation resources when Amplify's
high-level API does not expose a needed property:

```typescript
const backend = defineBackend({ auth, data });

// Auth override: Access the underlying CFN user pool resource
const cfnUserPool = backend.auth.resources.cfnResources.cfnUserPool;
cfnUserPool.policies = {
  passwordPolicy: {
    minimumLength: 12,
    requireLowercase: true,
    requireUppercase: true,
    requireNumbers: true,
    requireSymbols: true,
  },
};

// DynamoDB override: Access underlying CFN resources
const { cfnResources } = backend.data.resources;

// Enable point-in-time recovery
cfnResources.amplifyDynamoDbTables['Todo'].pointInTimeRecoveryEnabled = true;

// Change billing mode
cfnResources.amplifyDynamoDbTables['Todo'].billingMode = 'PAY_PER_REQUEST';

// Set TTL
cfnResources.amplifyDynamoDbTables['Todo'].timeToLiveAttribute = {
  attributeName: 'ttl',
  enabled: true,
};
```

The entry point for DynamoDB table overrides is
`backend.data.resources.cfnResources.amplifyDynamoDbTables['ModelName']`,
which exposes L1 CFN properties directly.

To add a **Global Secondary Index**, use `.secondaryIndexes()` in the
schema definition (the Amplify-native approach) rather than CDK overrides:

```typescript
const schema = a.schema({
  Todo: a.model({
    content: a.string(),
    status: a.string(),
    createdAt: a.datetime(),
  })
  .secondaryIndexes(index => [
    index('status').sortKeys(['createdAt']),
  ])
  .authorization(allow => [allow.owner()]),
});
```

See
[AWS Amplify Override docs](https://docs.amplify.aws/react/build-a-backend/add-aws-services/overriding-resources/)
for the full override API.

## Custom Outputs — Backend Only

Expose custom resource values to the frontend via `amplify_outputs.json`:

```typescript
backend.addOutput({
  custom: {
    analyticsTopicArn: topic.topicArn,
    apiEndpoint: 'https://api.example.com',
  },
});
```

Values appear under the `custom` key in `amplify_outputs.json`. Frontend
reads them from the Amplify configuration after `Amplify.configure()`.

## Face Liveness — Backend + Frontend

Verify user identity with Amazon Rekognition Face Liveness. Add IAM
permissions in `amplify/backend.ts`:

```typescript
import * as iam from 'aws-cdk-lib/aws-iam';

backend.auth.resources.authenticatedUserIamRole.addToPrincipalPolicy(
  new iam.PolicyStatement({
    actions: [
      'rekognition:CreateFaceLivenessSession',
      'rekognition:StartFaceLivenessSession',
      'rekognition:GetFaceLivenessSessionResults',
    ],
    resources: ['*'], // Rekognition session ARNs are generated at runtime — scope with conditions if needed
  })
);
```

**Frontend (React):**

```bash
npm install @aws-amplify/ui-react-liveness
```

```tsx
import { FaceLivenessDetector } from '@aws-amplify/ui-react-liveness';

<FaceLivenessDetector
  sessionId={sessionId}
  region="us-east-1"
  onAnalysisComplete={async () => { /* fetch results */ }}
/>
```

Create the session server-side via Rekognition SDK or a Lambda function,
then pass the `sessionId` to the component. See
[AWS Amplify Liveness docs](https://ui.docs.amplify.aws/react/connected-components/liveness)
for the full integration guide.

**Frontend (Swift — iOS 14+):**

Requires the `amplify-ui-swift-liveness` package and camera permission
(`NSCameraUsageDescription` in `Info.plist`). Add the package via Xcode SPM:
`https://github.com/aws-amplify/amplify-ui-swift-liveness`.

The backend must include a Cognito Identity Pool with an IAM role that
grants `rekognition:StartFaceLivenessSession` and
`rekognition:GetFaceLivenessSessionResults`.

See [Swift Liveness docs](https://ui.docs.amplify.aws/swift/connected-components/liveness)
for the full SwiftUI integration guide.

**Frontend (Android — API 24+):**

Add the dependency to `app/build.gradle.kts`:

```kotlin
dependencies {
    implementation("com.amplifyframework.ui:liveness:1.+")
}
```

Requires Jetpack Compose. The backend must include a Cognito Identity Pool
with an IAM role that grants `rekognition:StartFaceLivenessSession` and
`rekognition:GetFaceLivenessSessionResults`.

See [Android Liveness docs](https://ui.docs.amplify.aws/android/connected-components/liveness)
for the full Compose integration guide.

## Pitfalls

- **Duplicate stack names:** `backend.createStack()` names **MUST** be
  unique across the entire backend — reusing a name causes deployment failures.
- **Missing IAM permissions:** Geo, PubSub, and Face Liveness all require
  explicit IAM policies — Amplify does not auto-grant access to these
  services.
- **Geo CDK setup:** Geo (maps, place search, geofencing) requires CDK
  constructs — there is no `defineGeo()` in Amplify Gen2. Use
  `aws-cdk-lib/aws-location` directly as shown above.
- **PubSub endpoint:** You **MUST** configure the correct IoT endpoint for
  your region; using the wrong endpoint type causes silent connection
  failures.

## Links

- [Add AWS Services](https://docs.amplify.aws/react/build-a-backend/add-aws-services/)
- [Custom Resources](https://docs.amplify.aws/react/build-a-backend/add-aws-services/custom-resources/)
- [Overriding Resources](https://docs.amplify.aws/react/build-a-backend/add-aws-services/overriding-resources/)
