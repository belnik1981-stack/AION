# AION Changelog

## 0.3 trial — 2026-09-08

- Completed the READ-ONLY audit of the original runtime and provider path.
- Added hard API-call, iteration, time, input, token and response-size limits.
- Moved mutable state, memory and sanitized audit events under the ignored runtime directory.
- Added a no-network mock provider and cloud end-to-end smoke test.
- Restricted the web control surface to loopback with request limits, CSRF protection and HTML escaping.
- Added the Android plus Termux cloud trial runbook and ADR-001.
- Disabled implicit task execution from legacy command entry points.

## 0.2 — historical

- Added the initial multi-agent pipeline and local server.
