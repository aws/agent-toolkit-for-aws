# AI

> **Prerequisites:** Backend defined in `amplify/backend.ts` with `defineBackend({ auth, data })`.

## Model Selection

Use `a.ai.model()` to select an AI model in both `a.conversation()` and `a.generation()` routes. Pass a human-readable model name string:

```typescript
aiModel: a.ai.model('Claude Sonnet 4.5')
```

For the full list of supported models, see [AI Concepts: Models](https://docs.amplify.aws/react/ai/concepts/models/).

Key constraint: `a.generation()` routes only support Anthropic (Claude) models. `a.conversation()` routes work with any supported model.

For models not in the supported list, use the raw escape hatch: `aiModel: { resourcePath: '<bedrock-model-id>' }`.

Availability depends on the AWS region and Bedrock model access enablement.

### Bedrock Model Access

Some older or restricted models require explicit enablement in the AWS Bedrock console (Model access). On-demand foundation models (Claude Sonnet 4+, Nova) are available immediately. Amplify uses global inference profiles for cross-region model access.

If you get `AccessDeniedException: Could not access the model with the specified model ID`, check **Bedrock → Model access** in your region.

## Backend: Conversation Routes

Define multi-turn conversation routes in your data schema using
`a.conversation()`:

```typescript
// amplify/data/resource.ts
import { a, type ClientSchema } from '@aws-amplify/backend';

const schema = a.schema({
  chat: a.conversation({
    aiModel: a.ai.model('Claude Sonnet 4.5'),
    systemPrompt: 'You are a helpful assistant.',
  })
  .authorization(allow => allow.owner()),
});
```

## Backend: Generation Routes

Use `a.generation()` for single-turn (stateless) inference.

```typescript
const schema = a.schema({
  summarize: a.generation({
    aiModel: a.ai.model('Claude Sonnet 4.5'),
    systemPrompt: 'Summarize the provided text concisely.',
    inferenceConfiguration: { maxTokens: 500, temperature: 0.3 },
  })
  .arguments({ text: a.string().required() })
  .returns(a.customType({ summary: a.string() }))
  .authorization(allow => allow.authenticated()),
});
```

**Authorization constraints (these cause TypeError at CDK assembly if violated):**

- **Conversation routes** (`a.conversation()`) require `allow.owner()` authorization — `allow.authenticated()` and other non-owner strategies throw a TypeError at CDK assembly time.
- **Generation routes** (`a.generation()`) require non-owner authorization (`allow.authenticated()`, `allow.guest()`, `allow.group()`, or `allow.publicApiKey()`) — `allow.owner()` throws a TypeError at CDK assembly time.

These constraints are asymmetric and frequently confused. Getting them wrong
causes the CDK synthesis to fail with a non-obvious TypeError.

> **Security:** Conversation history sent to Amazon Bedrock may contain PII. Do not log full request/response payloads in production. Enable CloudWatch Logs encryption (KMS) and set appropriate retention policies for any logs that may capture inference data.

### Backend Integration

AI conversation and generation routes are part of your data schema. Import into `amplify/backend.ts`:

```typescript
import { defineBackend } from '@aws-amplify/backend';
import { data } from './data/resource';

defineBackend({ data }); // AI routes live inside the data schema
```

## Backend: AI Tools

Attach Lambda functions as tools to conversation routes so the AI model
can invoke them:

```typescript
import { myToolFunc } from '../functions/my-tool/resource';

const schema = a.schema({
  chat: a.conversation({
    aiModel: a.ai.model('Claude Sonnet 4.5'),
    systemPrompt: 'You are a helpful assistant with tool access.',
    tools: [
      {
        name: 'getWeather',
        query: a.ref('getWeather'),
        description: 'Get current weather for a city',
      },
    ],
  })
  .authorization(allow => allow.owner()),

  getWeather: a.query()
    .arguments({ city: a.string().required() })
    .returns(a.customType({ temp: a.float(), condition: a.string() }))
    .handler(a.handler.function(myToolFunc))
    .authorization(allow => allow.authenticated()),
});
```

Define the tool function with `defineFunction` (see
[functions-and-api.md](functions-and-api.md)).

## Frontend: React AI UI

Install the AI UI package:

```bash
npm install @aws-amplify/ui-react-ai
```

Set up hooks and render the conversation component:

```tsx
import { generateClient } from 'aws-amplify/data';
import { createAIHooks, AIConversation } from '@aws-amplify/ui-react-ai';
import type { Schema } from '../amplify/data/resource';

const client = generateClient<Schema>();
const { useAIConversation } = createAIHooks(client);

export default function Chat() {
  const [
    { data: { messages }, isLoading },
    handleSendMessage,
  ] = useAIConversation('chat');

  return (
    <AIConversation
      messages={messages}
      isLoading={isLoading}
      handleSendMessage={handleSendMessage}
    />
  );
}
```

## Frontend: Manual Client

For programmatic access without the pre-built UI:

```typescript
const client = generateClient<Schema>();

// List conversations
const { data: conversations } = await client.conversations.chat.list();

// Create a new conversation
const { data: conversation } = await client.conversations.chat.create();

// Send a message
const { data: message } = await conversation.sendMessage({
  content: [{ text: 'Hello!' }],
});
```

Pagination: use `limit` and `nextToken` parameters on `.list()`.

## Streaming

Subscribe to streaming responses for real-time token delivery:

In React, wrap in `useEffect` and return the cleanup function:

```tsx
useEffect(() => {
  const sub = conversation.onStreamEvent({
    next: (event) => console.log(event),
    error: (err) => console.error(err),
  });
  return () => sub.unsubscribe();
}, [conversation]);
```

> **UI note:** Amplify AI Kit provides pre-built UI components for React and
> React Native only. Flutter, Swift, and Android apps can invoke AI
> conversation/generation routes via manual GraphQL client calls — see
> [data-mobile.md](data-mobile.md) patterns for the equivalent approach.

## Pitfalls

- **Message content structure:** Both `sendMessage('Hello')` (string) and
  `sendMessage({ content: [{ text: 'Hello' }] })` (object) are valid. Use
  the object form when sending images or tool results.

## Links

- [AI Overview](https://docs.amplify.aws/react/ai/)
- [Set Up AI](https://docs.amplify.aws/react/ai/set-up-ai/)
- [Conversation UI](https://docs.amplify.aws/react/frontend/ai/conversation/)
- [Generation UI](https://docs.amplify.aws/react/frontend/ai/generation/)
