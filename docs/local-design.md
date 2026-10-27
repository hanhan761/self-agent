# Local edition architecture and upstream boundary

Pinned backend: [MCP Memory Service 12.4.0](https://github.com/doobidoo/mcp-memory-service/tree/v12.4.0), Apache-2.0.

The upstream storage schema also calls its content table memories and is not compatible with Self Agent's existing canonical schema. The local edition keeps one authoritative memory.sqlite3 (owners, projects, raw evidence, revisions, expiration, corrections, forget/undo, queues) and replaces the Mem0/Qdrant projection with a rebuildable MCP Memory Service local-vectors.sqlite3. This is an explicit implementation adjustment to avoid rewriting or losing validated evidence and lifecycle data. The optional Obsidian editor is not a dependency; Markdown is not a second source of truth.

Reused upstream components: SQLite-vec persistence/migrations, scoped retrieve_hybrid (BM25 + vectors), _check_semantic_duplicate for candidate nomination, store_batch for batched embeddings/commits, and ONNX tokenizer/embedding/pooling. The version-pinned adapter supplies an offline model directory, fixed CPU provider/thread budget, and disables storage-time semantic discarding and implicit model/provider fallback. Semantic duplicate detection is used to nominate candidates; it cannot discard or merge canonical IDs. Canonical reconciliation remains native XJTU only. Local capture reuses Self Agent's existing SDK-independent client adapters, with durable filesystem batches replacing synchronous Stop uploads. SDK 1.30.0 is pinned for the local runtime because MCP Memory Service declares mcp<2; Self Agent's five MCP tools also remain compatible with its previous SDK 2.3 server runtime.

SQLite projection keys incorporate owner, project, canonical ID and version. Search scopes are enforced by upstream SQL tags and rechecked against authoritative owner/project/status/expiration; stale projections cannot revive forgotten data. Source batches and canonical jobs are idempotent. A successful inbox fsync precedes cursor advancement. Retried captures use stable external IDs. Pre-install history is not harvested automatically.

XJCode's Windows login helper and DPAPI format are reused. Named-pipe login accepts only the current Windows SID, verifies a random nonce, encrypts the returned identity with DPAPI, then acknowledges the helper. Native model discovery uses only the selected account and personal workspace, never creates workspaces implicitly, and fixes an account fingerprint. No API credentials enter URLs, process arguments, Git or release assets. A cancelled login leaves existing credentials intact. Discovery/preflight failure leaves jobs pending; an interrupted or unconfirmed paid generation stays uncertain rather than silently paying for replay.

Local service binds to 127.0.0.1, checks Host/Origin and uses a private device token. Optional browser access uses a short-lived, owner-private HTML POST to exchange a one-use ticket for an HttpOnly cookie; the ticket never enters the URL. Uninstall stops only the authenticated local service and removes owned settings while retaining knowledge files. The old remote service remains available for rollback.

There is no supported silent bypass of Codex hook review. Installing config and successfully running a Hook subprocess are separate from the host's actual trusted lifecycle activation. Host verification must be reported independently.

## Automatic admission and simple local management

Direct user statements of durable facts, requirements, preferences and confirmed choices are eligible for automatic activation without a remember command. The native extractor preserves user intent and tense; assistants cannot certify their own success as user facts. Complete-response validation, literal user evidence, conflict handling, expiry and automatic non-resurrection remain enforced. Uncertain items are excluded from ordinary recall without requiring a review workflow.

Existing SessionStart and UserPromptSubmit commands also fsync local input batches before recall. Stop captures the remainder with the same cursor, so no new hook definitions or trust edits are required. One bounded prior assistant answer provides confirmation context; assistant-only batches are retained as sources without enqueuing another generation. APScheduler checks capture every 0.5 seconds, generation every 0.5 seconds and projections every second, each on a separate one-thread executor.

Local mode serves a dedicated single-page manager: all-project list by default, literal-content management search, 5-second visible-page refresh, direct add/edit/remove, and an explicit rejoin action. Source/history/import/backup are secondary. Cross-project management listing is an intentional user view; agent recall keeps its existing project boundary. Only the explicit restore endpoint permits a removed row to reactivate, with owner/version/expiry checks; automatic extraction and backup restore do not gain that ability.

## Scale and relevance boundary (0.2.1)

| Concern | Mature component actually called | Self Agent boundary |
| --- | --- | --- |
| Candidate retrieval | MCP Memory Service 12.4.0 retrieve_hybrid | Hash-scoped owner/project live stores, followed by canonical eligibility/version checks |
| Duplicate nomination | Upstream _check_semantic_duplicate + hybrid retrieval | Both live/archive stores; bounded canonical candidates; native XJTU evidence-based equivalence/replacement |
| Projection throughput | Upstream store_batch | 128-record batches, canonical version acknowledgement; projections can be deleted and rebuilt |
| Relevance after retrieval | FlashRank 0.2.10 Ranker.rerank + BGE base INT8 ONNX | At most 24 canonical candidates, fixed CPU 2 threads, offline pinned weights, score >= 0.2; no forced results |
| Scheduling | APScheduler 3.11.3 BackgroundScheduler + three ThreadPoolExecutors | SQLite domain jobs remain durable, MemoryJobStore holds only recurring wakeups; coalesce/max_instances prevent stacked executions |
| Resource coordination | filelock 4.2.4 + SQLite WAL + fsync batches | App-specific queue/data/free-disk budgets; pause without advancing capture cursor |
| Canonical lookup | SQLite FTS5 native rank and indexed scopes/deadlines | No Python full-table fuzzy comparison; fetch only a bounded candidate pool |

The reranker adapter supplies an already verified offline ONNX session and delegates pair tokenization, inference, sigmoid scoring and sorting to FlashRank. It never invokes a local generative model or downloads a fallback. Embedding scores are upstream normalized relevance (1 - cosine_distance/2), not calibrated probabilities. BGE scores are also not an accuracy guarantee. If reranking is unavailable, recall degrades to strong literal matches and reports rerank_state; it does not inject arbitrary vector neighbors. Model identity and checksums: [reranker-model.json](reranker-model.json).

Normal recall searches live stores. Archive stores preserve superseded, candidate and forgotten nominations, including semantically equivalent removed records; the lifecycle still blocks automatic resurrection. Same-meaning cross-kind extraction can attach evidence to the original canonical kind, while cross-kind replacement remains forbidden. A concurrent edit/remove during reranking is checked again before returning context.

The local installer defaults to an 8 GiB mutable-data budget; generic Config defaults to 2 GiB. Both reserve at least 512 MiB free disk. Inbox caps are 1,000 batches / 64 MiB; pending/running jobs cap at 1,000. Resource estimates are conservative, cached for at most two seconds under a cross-process lock; they are application backpressure, not filesystem quotas or protection against other applications filling the disk. SQLite read failure closes ingestion. Already committed batches may drain even while space is constrained. No automatic deletion of knowledge.

A complete validated extraction and per-item progress checkpoint are committed before application. Safe infrastructure deferrals resume from that checkpoint without repeating extraction. A failed/unknown native request remains failed/uncertain for explicit retry. APScheduler never owns paid request replay. Native-model acceptance, scale fixtures, privacy/lifecycle/restore regressions, browser checks and host trust are recorded separately in [scaling-acceptance.json](scaling-acceptance.json).

SessionStart has no concrete query: /v1/context uses bounded indexed SQLite reads of confirmed preference/decision/procedure defaults, with scope/lifecycle and project overrides. It does not rerank fabricated generic search terms. UserPromptSubmit uses hybrid retrieval and the relevance gate. Projection acknowledgement is asynchronous; frozen acceptance waits for canonical projection versions before asserting semantic recall.
