# AION

Version: 0.3 trial  
Status: bounded cloud-trial preparation

AION is a modular AI orchestration prototype developed for Android and Termux control. The current trial branch prioritizes explicit execution limits, provider independence, separation of Truth from mutable memory and reproducible tests.

## Current execution paths

- trial_cli.py single — one bounded provider request from a UTF-8 prompt file.
- trial_cli.py pipeline — bounded Planner, Analyst, Critic and Synthesizer flow.
- server.py — loopback-only control page; remote use requires an SSH tunnel.
- AION_PROVIDER=mock — deterministic no-network test path.

## Mandatory order

1. Run the offline workflow and local harnesses.
2. Review the recorded limits and Truth checksums.
3. Make one supervised live provider call.
4. Stop on any failed invariant.
5. Do not merge into master until the result is reviewed.

The exact commands and acceptance criteria are in docs/TRIAL_RUNBOOK_CLOUD_TERMUX.md. The trial architecture decision is in docs/adr/0001-cloud-trial-safety-boundary.md. The current verified state is in docs/PROJECT_STATE.md.

The divergent agents-sdk-adapter-20260908 branch and EGDE runtime integration are outside this trial boundary.
