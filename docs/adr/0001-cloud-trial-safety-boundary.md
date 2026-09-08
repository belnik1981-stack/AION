# ADR-001 — Safety boundary for the first cloud trial

Status: ACCEPTED AND OFFLINE-VERIFIED  
Date: 2026-09-08  
Scope: branch trial-readiness-2026-09-08

## Decision

The first cloud trial uses only the audited trial branch. It does not merge the divergent agents-sdk-adapter-20260908 branch and does not perform EGDE runtime integration.

The executable boundary is frozen as follows:

- Truth remains tracked and read-only through the runtime API.
- Mutable state, episodic memory and audit events are written only under the ignored runtime directory.
- One single-cycle command can make at most one provider call.
- The multi-role pipeline can make at most seven provider calls and at most two critic/synthesis iterations.
- Each provider request has a 20-second socket timeout.
- Each pipeline has a 90-second inter-call deadline and is wrapped by an external 120-second process timeout during the first live test.
- Prompt, request body, generated token count and provider response bytes have explicit ceilings.
- Provider HTTP bodies and credentials are never included in application errors or audit events.
- The web control surface binds only to loopback. Remote access is through an SSH port forward.
- A deterministic mock provider is the mandatory first cloud execution path.
- No retry is automatic.
- Every trial invocation requires an explicit task from a prompt file or protected local form.

## Reason

The previous code loaded max_iterations and timeout_seconds, but did not enforce a total API-call budget or workflow deadline. The server was not safe to expose from a cloud host, mutable state was mixed with tracked repository data, and legacy entry points could trigger an implicit request.

## Alternatives considered

1. Merge the Agents SDK and EGDE branches now — rejected because they have not passed this branch's audit and the histories diverge.
2. Expose the web UI publicly with a bearer token — rejected because it adds an unnecessary internet-facing attack surface.
3. Begin with a real provider call — rejected because a no-network end-to-end run proves the local boundaries first.
4. Containerize immediately — deferred because a direct Python virtual environment is simpler for Android plus Termux control and sufficient for this bounded test.

## Consequences

The first test proves startup, request flow, execution boundaries, private state separation, Truth invariance and safe stopping. It does not prove factual quality, external provider availability, model terms, long-running reliability or public multi-user operation.

## Actual result

Commit 25819306579cda867ddcfa28e318625e9623f34e passed GitHub Actions run 34265828578 on Ubuntu 24.04.4 and Python 3.11.16.

Observed results:

- preflight passed;
- all Python files compiled;
- architecture harness passed;
- negative safety harness passed;
- loopback server completed an end-to-end mock request;
- Truth files remained unchanged;
- repository permission in the workflow was read-only;
- no external model API was contacted.

Status remains READY WITH CONDITIONS until one supervised external provider call passes the runbook acceptance criteria.
