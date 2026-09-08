# PROJECT CHECKPOINT — AION cloud trial preparation

Date: 2026-09-08  
Project / branch: AION / trial-readiness-2026-09-08  
Audited base commit: b509ef540318f87cf33a03c53091c2a66b3c4647  
Current phase: minimal safety implementation after completed READ-ONLY audit

## Verdict

NOT READY until the new offline cloud workflow completes successfully. If it passes, the branch becomes READY WITH CONDITIONS for one manually supervised live provider call.

## Confirmed

- FACT — master remains at 540957cc3114f060dadeec90284b2366fb81183e.
- FACT — trial-readiness-2026-09-08 was three commits ahead of master at the audit point.
- FACT — agents-sdk-adapter-20260908 diverges from the trial branch and carries 23 separate commits; it is excluded from this test.
- VERIFIED — actual flow is Engine or Pipeline → core.llm → providers.registry → provider → external API.
- VERIFIED — provider configuration comes from AION_PROVIDER, AION_API_URL, AION_API_KEY, AION_MODEL and bounded non-secret limits.
- VERIFIED — the old provider layer had a per-request timeout but no enforced total API-call budget or workflow deadline.
- VERIFIED — the old server inserted stored values into HTML without escaping and had no request-size or CSRF boundary.
- VERIFIED — the supplied AION/EGDE research archive contains documentation and provenance material, not a replacement current runtime tree.

## Decision

- DECISION — freeze the first trial to the trial-readiness branch and the boundary in docs/adr/0001-cloud-trial-safety-boundary.md.
- DECISION — use the mock provider for the first end-to-end cloud run.
- DECISION — keep the UI loopback-only and access it through an SSH port forward.
- DECISION — keep EGDE runtime integration and the Agents SDK branch outside this test.

## Implemented, awaiting observed workflow result

- explicit API-call, iteration, time, prompt, request, token and response-size limits;
- private ignored runtime state and audit path;
- sanitized provider failures;
- mock provider;
- loopback Host and bind checks, CSRF token and HTML escaping;
- pinned PyYAML dependency;
- offline architecture, negative safety and end-to-end server smoke tests;
- a five-minute GitHub Actions cloud job with read-only repository permission;
- Android plus Termux cloud runbook.

## Open

- OPEN — the workflow result for the implementation commit.
- OPEN — one real provider call using a test-limited credential.
- OPEN — actual cloud host identity, OS, Python version and SSH account.
- OPEN — review and possible reconciliation of the divergent Agents SDK branch.
- OPEN — architecture freeze for EGDE integration; ADR-001 freezes only the first trial boundary.

## Do not count as complete

- factual-quality validation;
- evidence-weighted consensus;
- production authentication or public web exposure;
- provider availability, free-model stability or terms;
- long-running autonomous operation;
- merge into master.

## Last successful test

The prior test_current_architecture.py harness passed without a real API call according to the earlier branch work. The new safety and cloud tests have not yet produced observed CI evidence.

## Next action

Observe the first workflow run. Completion criterion: compile, diagnostics, architecture harness, negative safety harness, loopback cloud smoke and Truth-diff check all pass on the same commit.
