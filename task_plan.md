<!-- Current verified state (2026-10-28): local-v0.2.1 / 0a578758354b is deployed on D and publicly published; 137 tests, scale/native/frozen/MCP/browser checks passed. Three current Codex hooks remain enabled/trusted. Legacy 4090 deployment is preserved. -->

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
5. Migrate current device after isolated acceptance; document and push GitHub — complete; local-v0.2.0 published, installer checksum verified by GitHub.

Preserve server deployment and unrelated client configuration. Human Codex hook trust/reload remains a host-controlled step. No personal history bulk import.

## D drive migration — 2026-10-27
1. Measure storage and preserve connection settings — complete.
2. Stop local service; copy private installation and release artifacts to D with verification — complete.
3. Activate compatible directory junctions; verify database, runtime, MCP and unchanged settings — complete.
4. Remove verified former C copies and measure reclaimed space — complete; ~14.4 GiB freed; 15.5 MiB of locked legacy binaries scheduled for owned RunOnce cleanup.

## Live Hook verification and Windows path fix
1. Check configuration, trust and actual-session capture evidence — complete; enabled/trusted configuration exists, automatic capture was absent.
2. Reproduce extended-path rejection and add privacy/deduplication regressions — complete.
3. Fix source and hot-update installed D runtime without changing hook definitions — complete; 108 tests, actual isolated pythonw hook, installed checksums passed.
4. Observe current-thread automatic Stop after final reply — observer active; requires event after this turn ends.

## PowerShell Hook exit-1 fix
1. Reproduce actual shell failure rather than direct-process success — complete.
2. Fix invocation, per-hook executable detection and ownership recognition — complete.
3. Verify real PowerShell capture/UTF-8 recall/deduplication; run complete tests — complete, 109 passed.
4. Update installed D runtime/owned hook commands and preserve unrelated settings — complete.
5. Host trust review and actual automatic-event verification — awaiting user /hooks review; native status is modified for all three definitions.

## Live Hook acceptance result
Host trust review is resolved (all three enabled/trusted). Genuine current-thread automatic Stop capture and native extraction are verified by the observer: one source, one done job, one candidate memory. Active production recall is not claimed for this candidate; isolated UTF-8 recall checks passed separately. Windows login autostart is configured and points through the compatibility junction to D storage.

## Automatic admission, simpler management and earlier capture
1. Diagnose actual counts/scopes and extraction/trigger rules — complete: 1 active + 1 candidate, five sources, three completed extraction jobs; capture occurs only on Stop and default UI hides project memories.
2. Default direct user facts/requirements/confirmed decisions to automatic admission, retaining evidence and forgotten/conflict safeguards — complete; actual native isolation produced 5 active records with zero approval requests.
3. Capture on message submission as well as Stop without changing trusted Hook definitions — complete; shared durable cursor, bounded confirmation context and no assistant-only generation.
4. Simplify local management to a live all-project memory list, search, manual add/edit/remove, secondary history/source/backup — complete; isolated real-browser CRUD/rejoin and live readonly desktop/mobile checks passed.
5. Test privacy/lifecycle/native extraction/browser; update D installation and bounded existing-source reprocessing — complete; 115 tests, 5537 installed checksums, 3 deliberate completed-source reprocesses and one incremental current-session catch-up, 7 real active memories and successful actual MCP recall.

## Scale hardening and GitHub sync — reuse-first revision
1. Audit pinned upstream MCP Memory Service capabilities and mature embedded task runners before extending custom logic — complete; actual pinned source APIs verified and integrated.
2. Integrate upstream bounded retrieval/hybrid/dedup primitives while keeping canonical ownership/evidence/lifecycle boundaries — complete.
3. Reuse mature APScheduler execution over authoritative SQLite tasks; add application-specific capacity and paid-request guards — complete.
4. Run isolated scale, relevance, privacy/lifecycle/restore and real model/browser acceptance — complete; 137 tests, 100k canonical / 10,007 vectors, 12 positive + 12 negative queries, 7-call native lifecycle and frozen/browser/MCP acceptance.
5. Update D installation without changing trusted commands, package a verified offline update, commit/push and publish GitHub artifacts — complete; D update and 5,559 checksums verified, three trusted hooks confirmed, source pushed and local-v0.2.1 public assets verified by server SHA-256.

## Authorized local historical absorption and real-corpus validation — 2026-10-28
1. Inventory authorized Codex/Claude historical sessions and existing import paths — complete.
2. Freeze a private D-drive manifest; exclude runtime/tool noise and credentials; preserve roles, project scopes, original times and existing deletions — complete.
3. Validate isolated chronological history and improve ingestion/reconciliation with mature components — complete.
4. Absorb validated historical knowledge into the live local space — complete; 635 items, 104 completed jobs; current counts 581 active / 25 candidate / 18 superseded.
5. Verify real-corpus relevance, privacy/lifecycle/restore and management — complete; 156 tests, actual browser/MCP, 12 independent paraphrases + 12 literal lookups + 12 scope checks + 4 unrelated queries. Private report remains on D; source synchronization follows.
