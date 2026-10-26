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
3. User-owned CNAME record — waiting for external DNS configuration.
4. Apply public cutover, verify outside Tailnet and switch client URL — pending DNS.
