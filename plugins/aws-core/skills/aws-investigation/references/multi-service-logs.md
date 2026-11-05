# Multi-service logs investigation

Use this when a request, alarm or incident spans several services or a pipeline of components.

## 1. Read every service's own logs

Find the log group of every service the request passes through: the caller, the service you were
asked about, and each downstream service. Query each one around the timestamp or by the request or
correlation ID, and take each service's outcome from its own logs, never from another service's.

## 2. Report fields exactly, per layer

When similar fields appear at different layers (request-context parameters and token claims,
request scopes and OAuth scopes, a service's own authorization result and its caller's), report
each one separately with its source, verbatim, including `null`, empty or missing values.

## 3. Count unique failed requests within the alarm's scope

1. Read the alarm's dimensions (operation, caller, endpoint, stage) and its breach window from the
   alarm definition and history.
2. Keep only log records that match all dimensions and fall inside the window.
3. Group them by request or correlation ID and follow each ID to its final outcome; a request that
   succeeded on a retry is not a failure.
4. Report the number of unique failed requests separately from the number of raw error records,
   say that repeated records of one ID are retry attempts, and list the qualifying IDs.

## 4. Place the failure boundary per event

For each event, decide separately where it was lost: it never reached the service (upstream loss),
or the service received it and handed it off but the customer saw no result (downstream loss). If
the events differ, report both boundaries and both escalation paths. Never rule out the downstream
team when your logs show a successful handoff without a customer result.
