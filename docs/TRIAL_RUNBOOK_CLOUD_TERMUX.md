# AION first cloud trial — Android and Termux runbook

This runbook performs one offline cloud smoke test first, then one controlled live provider call. Do not merge the branch into master until both stages are reviewed.

## Fixed target

Repository: belnik1981-stack/AION  
Branch: trial-readiness-2026-09-08  
Python: 3.11 or newer supported version  
Network UI: loopback only  
Remote control: SSH tunnel from Termux

Because the repository is private, the cloud host needs a read-only GitHub deploy key or an authenticated GitHub CLI session. Do not put a personal access token in a clone URL.

## Stage 1 — connect from Termux

Run these commands in Termux:

    pkg update
    pkg install openssh
    ssh CLOUD_USER@SERVER_IP

Replace CLOUD_USER and SERVER_IP with the actual cloud account values.

## Stage 2 — prepare the cloud host

Run these commands after the SSH connection, in the cloud shell:

    sudo apt-get update
    sudo apt-get install -y git python3 python3-venv
    git clone --branch trial-readiness-2026-09-08 --single-branch git@github.com:belnik1981-stack/AION.git
    cd AION
    python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt

If the clone asks for GitHub credentials, stop. Configure a read-only deploy key or device authentication; do not paste a token into the command.

## Stage 3 — mandatory offline checks

Run from the AION directory on the cloud host:

    export AION_PROVIDER=mock
    export AION_RUNTIME_DIR="$PWD/runtime"
    export PYTHONPATH="$PWD"
    python -m core.diagnostics
    python -m compileall -q .
    python tests/harness/test_current_architecture.py
    python tests/harness/test_trial_safety.py
    python tests/harness/cloud_smoke.py
    sha256sum knowledge/truth/truth.json knowledge/truth/system.yaml

Required result: every command exits successfully; both safety scripts print PASS; no external model API is contacted.

## Stage 4 — create a protected provider environment

Run from the cloud shell:

    mkdir -p "$HOME/.config/aion"
    chmod 700 "$HOME/.config/aion"
    nano "$HOME/.config/aion/aion.env"

Enter the following lines inside the editor, not as a shell command:

    AION_PROVIDER=openai_compatible
    AION_API_URL=https://openrouter.ai/api/v1
    AION_MODEL=openrouter/free
    AION_API_KEY=PASTE_THE_TEST_KEY_HERE
    AION_MAX_TOKENS=800
    AION_BIND=127.0.0.1
    AION_PORT=8080

Save the file, then run:

    chmod 600 "$HOME/.config/aion/aion.env"
    set -a
    . "$HOME/.config/aion/aion.env"
    set +a
    python -m core.diagnostics

The key must never be printed, committed, pasted into a command, or sent in chat.

## Stage 5 — one live bounded call

Before the live request, record the Truth hashes:

    sha256sum knowledge/truth/truth.json knowledge/truth/system.yaml > /tmp/aion-truth-before.sha256
    nano "$HOME/aion_trial_prompt.txt"

Enter a harmless test task in the editor, for example: return a short answer stating that this is a connectivity test, without using tools or external actions.

Then run from the AION directory:

    timeout 120s .venv/bin/python trial_cli.py single --prompt-file "$HOME/aion_trial_prompt.txt"
    sha256sum -c /tmp/aion-truth-before.sha256
    tail -n 20 runtime/audit.jsonl

Acceptance conditions:

- exactly one provider call is recorded in the returned execution metadata;
- the process finishes within 120 seconds;
- both Truth files report OK;
- the audit contains start and completion events but no prompt, answer or credential;
- runtime/state.json exists and repository source files remain unchanged;
- there is no automatic retry after an error.

On HTTP 401, 402, 429, timeout, an unexpected model response, or any failed invariant: stop. Do not repeat automatically and do not proceed to the pipeline test.

## Stage 6 — optional loopback UI after the single call passes

On the cloud host, from the AION directory:

    set -a
    . "$HOME/.config/aion/aion.env"
    set +a
    ./start_app.sh

In a second Termux session:

    ssh -N -L 8080:127.0.0.1:8080 CLOUD_USER@SERVER_IP

Open this address on the Android device:

    http://127.0.0.1:8080

The application refuses an external bind. Stop the SSH tunnel and the server with Ctrl+C.

## Stop and recovery

A failed trial is not merged. Stop the process with Ctrl+C; if necessary, close the SSH session. Preserve runtime/audit.jsonl and the exact error status, but never copy the protected environment file into a report.

To restore the tested source branch after accidental local source edits:

    git status --short
    git diff

Review the diff before any recovery action. Do not use a destructive reset while unreviewed changes exist.

## Evidence to return for final review

Provide only:

- cloud OS and Python version;
- tested commit SHA;
- PASS or FAIL lines from the offline harnesses;
- single-call status and execution metadata;
- Truth checksum result;
- sanitized audit event names;
- provider HTTP status if a failure occurred.

Do not provide the API key, environment file, full prompt, or provider response body.
