<!-- Current direction: local Windows edition; the previous 4090 deployment is retained as legacy/rollback. -->

# Implementation plan

1. Repository initialization and first push — complete.
2. Central 4090 API, private website, native XJTU provider and memory lifecycle — complete.
3. MCP, client hooks, encrypted backup and selected history import — complete.
4. Automated checks, real API/MCP/provider acceptance and immutable deployment — complete.
5. Final documentation and GitHub synchronization — complete.

Scope: a private authenticated website and central API on 4090. Generation uses the existing XJTU account; no generative model is deployed. SQLite is authoritative; CPU semantic indexes are rebuildable. Secrets and private data remain outside Git.

Acceptance: 53 tests passed; real MCP read/write, native extraction/answer and encrypted restore passed. Keyword Top5 30/30; paraphrase Top5 9/10. See docs/acceptance.json.

Remaining user-side product step: review the newly installed Codex hooks through /hooks and reload clients. Browser visual QA could not run because CUA exposed no browser surface; API checks do not substitute for it.

## Public HTTPS follow-up

1. Inspect current host, tunnel and DNS — complete.
2. Test and deploy HTTPS support, stage ingress and rollback — complete (55 tests).
3. User-owned CNAME record — complete; two public resolvers confirmed.
4. Apply public cutover, verify public HTTPS/auth/MCP and switch client URL — complete.

## CPA authentication and easier onboarding

1. Inspect CPA guide, key registry and policy contract — complete.
2. Read-only key authentication, isolation, revocation and one-use pairing — complete.
3. Key login UI, Windows setup bundle and hidden-input CLI — complete.
4. Checks — 64 tests passed; JavaScript and downloaded PowerShell syntax verified.
5. Immutable deployment and live isolated setup/MCP verification — complete.

## Paste-to-agent onboarding

1. Generate a one-use instruction immediately after CPA login — complete.
2. Public guide/checksum and automatic client bootstrap — complete.
3. Tests and off-host release — complete (68 tests).
4. Live full bootstrap in an isolated profile, MCP acceptance, final push — complete.

## Natural memory optimization

1. Structured evidence and scope extraction — complete.
2. Transactional reconciliation, expiration, provenance and reversible cleanup — complete.
3. Compatible APIs, website, v2 backup/restore and client changes — complete.
4. Regression tests and real model acceptance — complete (87 tests, 10 confirmed native calls across six cases). MCP/public acceptance follows deployment.
5. Off-host release, current-space cleanup, local upgrade and verification — complete. Final release 49ca2b97056d; 61.5-second locked observation, actual public Hook loop and current-device MCP passed. Current paired space contained zero old memories. Browser visual verification unavailable (no CUA browser surfaces).

Defaults: explicit changes auto-replace; personal preferences cross projects; legacy cleanup is reversible; explicit deadlines expire; facts decay at 180-day half-life with 0.8 floor. No guessed fact activation or automatic forgotten-memory resurrection.

## Local seamless edition — 2026-10-27

Goal: Windows local knowledge, Codex + Claude Code automatic recall/capture, native XJTU with protected XJCode login reuse, no server pairing.

1. Verify pinned MCP Memory Service 12.4.0 integration and runtime — complete.
2. Implement local setup, protected credentials, durable capture, service lifecycle — complete.
3. Package private Windows runtime/model/login helper and GUI installer — complete; ae1cf227eca9.
4. Automated/privacy/lifecycle/restore checks and actual local native/MCP/hook acceptance — complete; 104 tests, actual native extraction/correction, pythonw MCP, browser and port/restart checks. Human host trust/reload remains pending.
5. Migrate current device after isolated acceptance; document and push GitHub — device migration and verification complete; publishing GitHub release.

Preserve server deployment and unrelated client configuration. Human Codex hook trust/reload remains a host-controlled step. No personal history bulk import.
