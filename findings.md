<!-- Current direction: local Windows edition; the previous 4090 deployment is retained as legacy/rollback. -->

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

## Natural memory implementation

Current source ingestion slices serialized JSON by characters, losing role provenance for long conversations. Existing exact-content deduplication has no source aggregation or conflict resolution. Preserve legacy table layouts with additive side tables; extend archives to v2 while accepting v1. Current-device setup and authenticated stdio search already passed; host Hook trust remains a human step.

## Local edition research

User chose local-machine first and Codex + Claude Code. MCP Memory Service 12.4.0 is the selected pinned reusable backend (SQLite-vec + CPU ONNX); Basic Memory 0.24.1 no longer captures Stop, Claude-Mem 15.3.0 lacks native XJTU and has provider fallback, MemSearch documents Windows best-effort. XJCode local protected credentials exist; no credentials were printed. Codex already has inline Self Agent hooks; merge/remove by ownership to prevent double capture.

Integration adjustment: upstream SQLite uses a conflicting memories schema. Preserve one authoritative lifecycle/source database and use MCP Memory Service SQLite-vec as a rebuildable projection (replacing Mem0/Qdrant locally). This avoids unsafe historical schema rewrites and preserves all existing privacy/restore guarantees. The native provider remains the only generative path.

D-drive migration: the complete private Self Agent directory is about 10.4 GiB; ignored local release artifacts are about 3.9 GiB. D has about 44 GiB free. Migrate all Self Agent private state and local releases using verified copies and C directory junctions, preserving existing absolute client/startup paths and protected shared XJCode login.

Windows transcript compatibility: Codex persists extended-length paths. Resolve links before canonicalizing extended drive/UNC spelling for scope checks and cursor identity; retain the original resolved path for file I/O. Local and remote capture share this identity, so ordinary/extended aliases cannot create duplicate batches. Outside-home paths remain rejected.

PowerShell launch root cause: Windows Codex executes command hooks through PowerShell. JSON-quoted executable paths without the call operator cause ParserError/exit 1 before Python starts. This hidden environment also lacks a useful PATHEXT (PowerShell synthesizes only .CPL), so the command sets an executable-extension list only inside the hook subprocess and uses & with single-quote escaping. Genuine PowerShell capture and Chinese recall, rather than direct CreateProcess success, are required acceptance checks.

Reuse-first scale hardening: pinned MCP Memory Service 12.4.0 exposes retrieve_hybrid(store=...), retrieve(...), _check_semantic_duplicate(store=..., similarity_threshold=...) and store_batch(...). Its HybridMixin owns BM25/vector fusion and result batching; per-store filtering is explicit. APScheduler 3.11.3 is already in the offline lock/runtime and upstream consolidation scheduler; use its independent coalescing executors instead of adding another broker or custom dispatch loop. Keep canonical SQLite ownership/evidence/lifecycle and paid-uncertainty semantics; library dedup is used to nominate canonical matches, never to silently discard protected canonical data. Sources: pinned upstream sqlite_vec.py and mixins/{hybrid,retrieve,store}.py; APScheduler 3.x user guide.

## Mature-component verification and scale findings (2026-10-28)
- Upstream MCP Memory Service 12.4.0 now owns scoped hybrid retrieval, semantic duplicate nomination and batched projection writes; canonical SQLite remains authoritative. APScheduler 3.11.3 owns three bounded independent executor lanes; filelock 4.2.4 serializes resource reservations.
- First actual 10,007-vector acceptance caught poor rejection: 8/8 positives but only 2/6 irrelevant queries returned no result. Upstream relevance is 1-distance/2 for cosine distance, so it is not raw cosine. Do not pass min_confidence as a similarity threshold.
- FlashRank 0.2.10 was evaluated offline. Its provided MultiBERT artifact failed this bilingual fixture (including English paraphrases); it is not selected for release. Evaluating MIT BGE reranker base ONNX weights with the same mature FlashRank pairwise inference. No generative calls in scale/reranker calibration.
- SQLite FTS hidden rank ordering avoids unnecessary external sort; expiry now starts from an indexed non-null deadline range. Candidate Python row materialization stays at 25 in both 10k/100k fixtures.

- Frozen end-to-end acceptance caught a startup-query issue: strict reranking should not treat generic bootstrap words as a real question. SessionStart now reads bounded confirmed defaults from SQLite without semantic inference. Prompt recall retains upstream hybrid + FlashRank. The actual cross-client fixture also requires projection-version convergence before asserting semantic recall; source activation and projection completion are separate.

## Authorized historical absorption (2026-10-28)
- User explicitly authorized analysis/absorption of existing local history. Scope starts with supported same-user Codex/Claude conversation stores; no unrelated credentials or messaging-app databases. Private inventory, snapshots and analysis are kept on D outside Git.
- Metadata inventory: 291 Codex + 7 Claude JSONL files, approximately 9.3 GiB total; largest Codex session approaches 1 GiB. Existing import_recent skips files above normalized_messages 100 MiB cap and slices serialized JSON by characters. Need streamed role-aware envelopes, original timestamps and attributable project boundaries, without tool/runtime blobs or subagent-as-user contamination.

- Real history confirmed scope overgeneralization despite exact quote validation: a source quote can support a local task without supporting a global default. Retain original question context; narrow project requirements, quarantine one-off authorizations, and keep automatic admission for clearly grounded durable facts.
- Initial native task concurrency 32 concentrated failures; later observed one exact known HTTP 500/InternalError.Error wrapper reporting upstream 429. Reused shared RateGovernor for bounded pacing/backoff; no evidence for a specific RPM/TPM quota. Safe typed receipts retain action, outer HTTP status and known code without arbitrary response text.
- Invalid confirmed reconciliation can carry an unrelated target even with relation=independent. Reject unused/cross-scope/cross-kind targets during bounded validation. For explicit historical batches, exhausted relationship validation stores a sourced candidate and advances only that atomic item checkpoint; unknown transport outcomes remain uncertain.
- Portable v2 backup now includes optional owner-scoped project names and preserves destination custom names. Real-corpus restore and source evidence are tested separately from synthetic scale fixtures.

## Review management research — 2026-10-29
- Notion primary docs describe multiple filtered/sorted/grouped views over one database plus side peek detail; Obsidian primary docs organize local notes through properties and Bases; SiYuan provides document/block references. Adopt compact metadata views, stable navigation, a persistent detail inspector and source links rather than a full document editor or a new canonical store. Sources: https://www.notion.com/help/views-filters-and-sorts ; https://obsidian.md/help/bases ; https://obsidian.md/help/properties ; https://github.com/siyuan-note/siyuan .

- Live baseline confirmed 33 global vs 553 project active records, with matching API/SQLite counts. Overly restrictive intent classification, including a mixed project+future favicon requirement, explains missed reusable methods. New prompt recognizes semantic conditional defaults without requiring literal all-project keywords, while preserving single-artifact constraints, quotas and one-off authorizations.
- Scope audit evaluated 275 project preferences/procedures; 274 valid item verdicts (7 salvaged from complete validated replies), one unresolved left unchanged. 80 global suggestions were context-reviewed; 33 accepted for existing lifecycle simulation, with 3 equivalent merges and no original-time changes. Selected examples are kept private. Global active count 35 → 65 at application.
- Management uses exact_project=true for browsing; legacy listing/agent recall still include global defaults. Entire bulk selections are prevalidated for owner/version and committed atomically, including duplicate-target collision rollback. Real browser coverage includes mobile inspector, evidence, batch move, edit/forget/restore, label rename and type filters.

## Daily memory growth — 2026-10-29
- Count the first recorded active version per owned memory, rather than created/updated timestamps or current active-row counts. This keeps edits, merges and restore/remove operations from inflating daily additions, and distinguishes source history/restored/import-prefix records. Fixed Asia/Shanghai day bins and candidate/foreign-owner guards are exercised directly.
- Reused Chart.js 4.6.1 UMD from verified official npm package integrity; bundled @kurkle/color 0.3.2 and both MIT notices retained. No runtime CDN, date-adapter dependency or external request. Category dates use server-provided local day labels; accessible canvas plus text/table alternative follows official docs. Sources: https://www.chartjs.org/docs/latest/getting-started/integration.html ; https://www.chartjs.org/docs/latest/general/accessibility.html .
