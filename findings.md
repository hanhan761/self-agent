# Findings

- The requirement is a durable personal/project knowledge store independent of AI accounts: keep source evidence, versions, export/restore and explicit review of inferred candidates.
- The user's final hosting choice is the registered 4090 server. It hosts the private website, canonical SQLite data, queue and rebuildable indexes. Existing XJTU native HMAC handles generation; no generative LLM is installed.
- The allowed XJTU account and exact qwen3.8-max route were verified through complete live extraction and answer requests. No account/provider/model fallback is used.
- BGE-M3 cache was incomplete. The complete cached multilingual MiniLM-L12-v2 encoder works on CPU with 384-dimensional embeddings. Native generation and semantic recall are both operational.
- Mem0's current factory and config interfaces require a scoped adapter; current collection APIs require filters and top_k. Canonical SQLite status and owner/project checks remain authoritative even when semantic results are stale.
- The default yun 15% reserve exceeded available disk. For this explicitly bounded small-service installation, deployment retains at least 100 GiB and limits artifact, expanded files and data; this does not authorize model downloads or deletion of other services.
- Private endpoint: http://100.95.110.75:8766, reachable through the existing Tailnet. No public DNS/tunnel/firewall was changed.
- Claude Code and Codex configs are installed with backups. Codex requires the user's /hooks trust review; this must not be bypassed.
- Acceptance: 53 automated checks; live MCP, native provider, backup verification and synthetic restore passed. Retrieval checks: keyword 30/30 and paraphrase 9/10 Top5. One storage-engine paraphrase missed.
- Browser visual QA remains unperformed because no CUA browser surface was available.
- Initial and implementation pushes were verified successful; origin/main contains the deployed application release.
