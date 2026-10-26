# Progress

## Completed 2026-10-26

- Initialized main, linked hanhan761/self-agent and verified the initial push.
- Read the authorized recent Chen Yan conversation; implemented independent, portable personal/project memory with provenance, revisions and candidate review.
- Deployed the private website/API at http://100.95.110.75:8766 on the registered 4090 host, using its existing native XJTU account for all generation and extraction.
- Prepared Linux dependencies off-host; activated immutable verified releases without running build/install tools on the server. Reused the complete cached multilingual MiniLM encoder on CPU; downloaded no model weights.
- Active application release: 0874a65774ad24be49cea64b8083fccf88508dfd. Latest observation: active/running for 562 seconds, zero restarts, about 1.14 GiB memory, 108.89 GiB disk free, zero unfinished jobs and zero pending projections. Three sampled unrelated services remained active.
- Installed Claude Code and Codex MCP/hooks while preserving and backing up existing configuration. Codex hook trust remains controlled by the product /hooks UI.
- Encrypted and independently verified 352 local history/rule files (about 9.3 GB raw). Imported only 2 related sources; skipped 279 unrelated/unattributed files. Both extraction jobs completed, producing 17 candidates for user review.
- Reconciled one failed extraction from its privately retained complete provider response after fixing decoded evidence validation; no extra generation was needed.
- Verified an encrypted portable export containing 17 memories and 2 sources, excluding authentication tables. Live synthetic-account restore preserved existing memories without duplication.
- 53 pytest checks passed. JavaScript syntax passed. Live stdio MCP initialized, exposed 5 tools, and wrote/recalled remote memory. The native qwen3.8-max route completed extraction and a grounded answer.
- Real isolated retrieval: keyword Top5 30/30; paraphrase Top5 9/10, with one database paraphrase missed. Semantic projection is healthy; this small synthetic check is not a general accuracy guarantee.
- Browser visual QA unavailable: CUA inventory had no enabled browsers. This remains explicitly unverified.

## Compatibility fixes validated

- MCP 2.3 MCPServer API; Mem0 2.2.1 scoped filters/top_k; narrowly scoped custom LLM config; writable MEM0_DIR under the protected service state.
- Windows private-root fallback when hidden child processes lack LOCALAPPDATA; hidden child process launches; normalized serialized evidence and one bounded formatting repair after complete replies.

Private credentials, archive keys, source histories and test accounts are outside the repository.

- Deployed application commits were pushed successfully to origin/main. The owned local preview was stopped after verification; the disposable bootstrap credential copy was removed. Permanent private login and backup keys remain available.

## HTTPS public access — 2026-10-26

- User selected self-agent.matterswarm.com. The 4090 origin and existing Cloudflare Tunnel are healthy; three existing public routes returned 200.
- Built and deployed release 78e83d3367b2 off-host, retaining 0874a65774ad for rollback. Tests: 55 passed, including HTTPS login/key access and preserving existing routes.
- Added a validated, reversible public configuration helper; stage-only candidate passes cloudflared ingress validation. Public cutover has not been applied, preserving current clients until DNS exists.
- External prerequisite: no DNS record exists and no local DNS API credential or CUA browser is available. Asked the user to add the exact proxied CNAME. No Cloudflare secrets were requested or accessed.
- Once DNS is present: apply the prepared public configuration, verify TLS, authentication/key access and unrelated routes, observe service, then switch local client URL and login instructions.

- User imported the CNAME. Two public resolvers returned the proxied addresses; applied the verified configuration and switched the origin to 127.0.0.1 with Secure cookies. Public TLS/root/health/login/key access, isolated write/read/search/forget and actual MCP stdio all passed.
- Observed 179 seconds with zero restarts; origin/tunnel and three existing public sites returned 200, sampled unrelated services remained active. Retained configuration backups and the previous application release.
- Updated this machine to the public HTTPS URL. Its campus DNS still returns cached NXDOMAIN; an explicit optional client proxy uses the already configured local network proxy without weakening certificate validation. Other devices can use the public URL directly.
- 55 tests passed after the client connectivity change. Browser visual QA remains unavailable. Public verification metadata and installation instructions updated.

## CPA key login and easier onboarding — completed

- Confirmed the intended service is https://cpa.matterswarm.com/guide. Its existing registry and permission store are read-only identity sources. No CPA original key is copied into self-agent state, an installer, logs or Git. No inference call is used to validate login.
- Added CPA key login, same-key isolated workspaces, explicit linking to an existing space, and revocation checks for sessions and derived device keys. CPA authentication never gains administrator privileges. Empty auto-created spaces can be deliberately linked; occupied spaces cannot be overwritten.
- Added ten-minute, one-use pairing and a Windows download package. Hidden-input setup exchanges a CPA key for a separate device key, writes its private file, and merges client settings automatically. Python 3.11+ remains a prerequisite; Codex hooks still require product trust review.
- Built client source ZIP and checksums off-host; deployed c4f7a42b2aa2 with artifact SHA-256 9b075cea2f1839240ffe6b93aa3350c01c5fb98350db0675729d1f867589cd68, retaining 78e83d3367b2. Registry loads 18 active identities and recognizes registered credentials in-process without exposing them.
- 64 tests passed, including account/project isolation, source-key disable/removal, fail-closed registry errors, administrator privilege protection, single-use/expired pairing and preserving existing client config.
- Live public package download/hash verification, invalid-key rejection, automatic setup for both clients in an isolated home, pairing replay rejection and stdio MCP write/recall passed. Downloaded PowerShell parsed successfully; the entire dependency-installing PowerShell script was not executed against the real user profile. Browser visual QA remains unavailable.
- CPA config and permission file checksums and source-container start times remained identical. Existing sampled websites and services remained healthy; source generation routing remains native XJTU.

## Paste-to-agent onboarding — completed

- CPA key login now opens the instruction generator. The user copies one short instruction to a local tool-using agent; it contains a ten-minute one-use pairing code, not the CPA key. The ZIP path is retained only as a fallback.
- Public guide and SHA-256 bootstrap metadata let the agent identify the OS/client and perform private setup. Pairing data travels over stdin and JSON bodies, never URL/process arguments. Codex trust review remains user-controlled.
- Complete live bootstrap exposed two network issues: the ingress rejects the default Python-urllib user agent, and default PyPI was unreachable in the isolated campus-network profile. Fixed with an honest connector user agent, proxy inheritance for subprocesses, and an HTTPS package index honoring explicit/existing settings (otherwise the Tsinghua mirror). Certificate checks remain enabled.
- 68 tests passed. Published final release edc17acfb7e0 from immutable artifact a9a1c3b33e376a69f77f3119860084290e8be48bf85b4a6cb36ef0bf56872a3d.
- Fully executed the final published bootstrap in an isolated Windows user profile in 37.8 seconds: downloaded/checksummed source, installed dependencies in a new environment, detected both clients, preserved the original model setting, paired and authenticated search successfully. Actual stdio MCP discovered five tools and wrote/recalled synthetic memory.
- Observed the service for 86.7 seconds with zero restarts; origin, tunnel, public login/key access and sampled existing sites passed. CPA source configuration/checksums and container start times remained unchanged. Browser visual QA remains unavailable.

Natural memory: added structured message batches, additive lifecycle/evidence/change tables, native scope/reconciliation validation, transactional update/merge/undo, expiry and bounded fact recency, v2 archives, and UI maintenance/history. Initial 74 tests pass. Follow-up edge tests cover concurrency, UTF-8 stdin and credential redaction. One controller edit used JavaScript index instead of indexOf (corrected before file write); node executable discovery needed (no global default path).

Natural memory validation: 87 automated tests and JavaScript syntax pass. Real native acceptance exposed and fixed missing scope constraints, same-reply deduplication, invalid override metadata (bounded repair), and topic retrieval. Final isolated qwen3.8-max run passed all six cases with 10 confirmed calls. No production user memories were used in model tests.

Public acceptance: actual hidden Windows Hook processes passed upload/extraction, UserPromptSubmit recall, SessionStart recall, natural correction and exclusion of the superseded preference. Synthetic identities were verified distinct from the current device identity. TLS jitter exposed the 1.8-second hook budget; increased bounded budgets and added frozen per-batch cursor recovery. 88 tests now pass. Initial program release passed 61.5 seconds of locked origin/public observation; a bounded client follow-up release is being prepared.

Natural memory delivery complete: final release 49ca2b97056d1f1cc572bc655cf687cc9c70e0b3, artifact SHA-256 a06bfa49904b2e3c38a5a45eaed719f90a49b89f12cadec0f62a10525cfff16f. Locked origin/public observation 61.5 seconds, NRestarts=0, CPA and Self Agent configurations unchanged. Current paired space backed up and cleanup completed with 0 records. Final verified client installed privately; original device identity, other Codex settings and other hooks preserved. Five stdio MCP tools and authenticated search passed. Browser surfaces unavailable; host Hook review/reload remains manual. A controller REPL variable shadowing interrupted packaging after a successful commit; restored the declared prior artifact from its manifest before continuing, without production mutation.
