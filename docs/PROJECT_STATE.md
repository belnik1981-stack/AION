# PROJECT CHECKPOINT — AION cloud trial preparation

Date and time: 2026-09-08 18:55 UTC  
Project / branch: AION / trial-readiness-2026-09-08  
Last code commit tested: 25819306579cda867ddcfa28e318625e9623f34e  
Cloud workflow run: 34265828578  
Scope: first bounded cloud trial

## Verdict

READY WITH CONDITIONS for one manually supervised live provider call.

This verdict does not authorize a public web deployment, autonomous long-running execution, a merge into master, or integration of the divergent Agents SDK and EGDE branches.

## Confirmed

- FACT — master remains at 540957cc3114f060dadeec90284b2366fb81183e.
- FACT — agents-sdk-adapter-20260908 diverges from the trial branch and carries 23 separate commits; it is excluded from this test.
- VERIFIED — actual flow is Engine or Pipeline → core.llm → providers.registry → provider → external API.
- VERIFIED — provider credentials are accepted only through AION_API_KEY and are not written to state, audit events or provider errors.
- VERIFIED — single-cycle execution is limited to one provider call.
- VERIFIED — the role pipeline is limited to two synthesis iterations, seven provider calls, a 20-second per-request timeout and a 90-second inter-call deadline.
- VERIFIED — input, prompt, HTTP request body, output token count and provider response bytes have validated ceilings.
- VERIFIED — mutable state, episodic memory and audit events are stored under the ignored private runtime directory.
- VERIFIED — the trial server rejects external bind, requires a loopback Host header, limits request bodies, requires a per-process form token and HTML-escapes stored content.
- VERIFIED — the supplied AION/EGDE research archive is documentation and provenance material, not a replacement runtime tree.
- VERIFIED — the GitHub cloud runner used Ubuntu 24.04.4 and Python 3.11.16 with read-only repository permission.

## Cloud evidence

Successful run: https://github.com/belnik1981-stack/AION/actions/runs/34265828578

Observed on the same commit:

- PRE-FLIGHT: PASS
- LOCAL ARCHITECTURE TEST: PASS
- TRIAL SAFETY TEST: PASS
- CLOUD LOOPBACK SMOKE TEST: PASS
- Truth diff check: PASS
- every workflow step: success

An earlier run, 34264959545, failed because direct test execution did not include the repository root in Python's import path. Commit 523bd28e8cb1f51c5929cf1415ed9d5127282c77 corrected the invocation and test bootstrap. Two subsequent full runs passed. The failed run is retained as provenance and is not presented as a core failure.

## Decisions

- DECISION — freeze the first trial to trial-readiness-2026-09-08 and ADR-001.
- DECISION — require the mock provider before any external provider call.
- DECISION — keep the UI loopback-only and reach it through an SSH port forward.
- DECISION — require an explicit prompt file; legacy entry points no longer start an implicit task.
- DECISION — keep EGDE runtime integration and agents-sdk-adapter-20260908 outside this test.

## Changed

- core/execution.py — enforced call and time budgets.
- core/llm.py and providers — bounded and sanitized provider path.
- core/engine.py and core/pipeline.py — explicit bounded execution with private audit metadata.
- memory/store.py — mutable memory separated from tracked Truth.
- server.py — loopback, request, CSRF and output-escaping boundary.
- start_app.sh and trial_cli.py — explicit, portable trial startup without filesystem key scanning.
- tests/harness — offline negative and end-to-end cloud tests.
- docs/TRIAL_RUNBOOK_CLOUD_TERMUX.md — exact Android plus Termux procedure.
- project_summary.txt — stale generated code/state snapshot marked superseded.

## Open

- OPEN — actual cloud host address, SSH account and observed host resources.
- OPEN — one external provider request with a test-limited credential.
- OPEN — provider availability and selected model at the time of the live call.
- OPEN — review and possible reconciliation of agents-sdk-adapter-20260908.
- OPEN — full EGDE architecture freeze and integration.
- OPEN — operating-system-level service sandboxing for any later persistent deployment.

## Do not count as complete

- factual-quality validation or evidence-weighted consensus;
- production authentication or public multi-user access;
- long-running autonomous execution;
- external tools or irreversible actions;
- merge into master.

## Last successful test

Workflow 34265828578 tested commit 25819306579cda867ddcfa28e318625e9623f34e. All steps succeeded and no real model API was contacted.

## Next action

Run Stage 1 through Stage 5 of docs/TRIAL_RUNBOOK_CLOUD_TERMUX.md on the chosen cloud host. Completion criterion: one external provider call, exactly one recorded API attempt, completion within 120 seconds, unchanged Truth checksums and a sanitized audit trail.
