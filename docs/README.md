# AION

Version: 0.3 trial  
Status: READY WITH CONDITIONS for one supervised live cloud call

AION is a modular AI orchestration prototype developed for Android and Termux control. The current trial branch prioritizes explicit execution limits, provider independence, separation of Truth from mutable memory and reproducible tests.

## Verified execution paths

- trial_cli.py single — one bounded provider request from a UTF-8 prompt file.
- trial_cli.py pipeline — bounded Planner, Analyst, Critic and Synthesizer flow.
- server.py — loopback-only control page; remote use requires an SSH tunnel.
- AION_PROVIDER=mock — deterministic no-network test path.

Commit 25819306579cda867ddcfa28e318625e9623f34e passed the full offline cloud workflow:
https://github.com/belnik1981-stack/AION/actions/runs/34265828578

## Mandatory order

1. Run the offline harnesses on the target cloud host.
2. Review limits and record the Truth checksums.
3. Make one supervised live provider call.
4. Stop on any failed invariant.
5. Do not merge into master until the live result is reviewed.

Exact commands and acceptance criteria: docs/TRIAL_RUNBOOK_CLOUD_TERMUX.md  
Architecture decision: docs/adr/0001-cloud-trial-safety-boundary.md  
Verified state: docs/PROJECT_STATE.md

The divergent agents-sdk-adapter-20260908 branch and EGDE runtime integration are outside this trial boundary.
