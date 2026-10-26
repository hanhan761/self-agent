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
