# AI

## Model Selection

Use `a.ai.model()` to select an AI model in both `a.conversation()` and `a.generation()` routes. Pass a human-readable model name string:

```typescript
aiModel: a.ai.model('Claude 3.5 Sonnet v2')
```

`a.ai.model()` accepts any supported model name:

- **Anthropic**: `'Claude 3 Haiku'`, `'Claude 3 Sonnet'`, `'Claude 3 Opus'`, `'Claude 3.5 Haiku'`, `'Claude 3.5 Sonnet'`, `'Claude 3.5 Sonnet v2'`, `'Claude 3.7 Sonnet'`, `'Claude Opus 4'`, `'Claude Sonnet 4'`, `'Claude Haiku 4.5'`, `'Claude Sonnet 4.5'`, `'Claude Opus 4.5'`, `'Claude Sonnet 4.6'`, `'Claude Opus 4.6'`
- **Amazon**: `'Amazon Nova Pro'`, `'Amazon Nova Lite'`, `'Amazon Nova Micro'`
- **Meta**: `'Llama 3.1 405B Instruct'`, `'Llama 3.1 70B Instruct'`, `'Llama 3.1 8B Instruct'`
- **Cohere**: `'Cohere Command R+'`, `'Cohere Command R'`
- **Mistral**: `'Mistral Large 2'`, `'Mistral Large'`, `'Mistral Small'`

For models not in the supported list, use the raw escape hatch: `aiModel: { resourcePath: '<bedrock-model-id>' }`.

Availability depends on the AWS region and Bedrock model access enablement.

> **Note:** `a.generation()` routes only support Anthropic (Claude) models. `a.conversation()` routes work with any supported model.

## Backend: Conversation Routes

Define multi-turn conversation routes in your data schema using
`a.conversation()`:

```typescript
// amplify/data/resource.ts
import { a, type ClientSchema } from '@aws-amplify/backend';

const schema = a.schema({
  chat: a.conversation({
    aiModel: a.ai.model('Claude 3.5 Sonnet v2'),
    systemPrompt: 'You are a helpful assistant.',
  })
  .authorization(allow => allow.owner()),
});
```

## Backend: Generation Routes

Use `a.generation()` for single-turn (stateless) inference.

> **MUST:** Only Anthropic (Claude) models support `a.generation()` routes. Non-Anthropic models (Amazon Nova, Meta Llama, Cohere, Mistral) work with `a.conversation()` only.

```typescript
const schema = a.schema({
  summarize: a.generation({
    aiModel: a.ai.model('Claude 3.5 Sonnet v2'),
    systemPrompt: 'Summarize the provided text concisely.',
    inferenceConfiguration: { maxTokens: 500, temperature: 0.3 },
  })
  .arguments({ text: a.string().required() })
  .returns(a.customType({ summary: a.string() }))
  .authorization(allow => allow.authenticated()),
});
```

**CRITICAL — Authorization Constraints:**

- **Conversation routes** (`a.conversation()`) **MUST** use `allow.owner()` authorization — `allow.authenticated()` and other non-owner strategies throw a TypeError at CDK assembly time (before deployment even begins).
- **Generation routes** (`a.generation()`) **MUST** use non-owner authorization (`allow.authenticated()`, `allow.guest()`, `allow.group()`, or `allow.publicApiKey()`) — `allow.owner()` throws a TypeError at CDK assembly time (before deployment even begins).

These constraints are asymmetric and frequently confused. Getting them wrong
causes the CDK synthesis to fail with a non-obvious TypeError.

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
    aiModel: a.ai.model('Claude 3.5 Sonnet v2'),
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

In React, **MUST** wrap in `useEffect` and return the cleanup function:

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

- **Conversation auth MUST be `allow.owner()`:** Using
  `allow.authenticated()` or any other non-owner strategy on
  `a.conversation()` throws a TypeError at CDK assembly time.
- **Generation auth MUST NOT be `allow.owner()`:** Using
  `allow.owner()` on `a.generation()` throws a TypeError at CDK assembly
  time. Use `allow.authenticated()`, `allow.guest()`, or `allow.group()`.
- **Missing AI route in data schema:** The conversation or generation
  route **MUST** be defined in your `a.schema()` — without it, the
  frontend client has no AI endpoint to call.
- **Model availability:** Not all Bedrock models are enabled by default —
  you **MUST** enable model access in the AWS console (Bedrock → Model
  access) before using a model in `a.ai.model()`.
- **Message content structure:** Both `sendMessage('Hello')` (string) and
  `sendMessage({ content: [{ text: 'Hello' }] })` (object) are valid. Use
  the object form when sending images or tool results.

## Links

- [AI Overview](https://docs.amplify.aws/react/ai/)
- [Set Up AI](https://docs.amplify.aws/react/ai/set-up-ai/)
- [Conversation UI](https://docs.amplify.aws/react/frontend/ai/conversation/)
- [Generation UI](https://docs.amplify.aws/react/frontend/ai/generation/)
