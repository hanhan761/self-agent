# Natural memory lifecycle

Normal conversations are captured only after the host's Hook trust review. The client sends redacted message envelopes with role, timestamp and stable IDs. Batches never split serialized JSON; long messages preserve role and provenance across fragments. Plain-text legacy sources remain supported but cannot independently prove a user's statement.

Native XJTU extraction classifies personal, project and session-only information. Explicit personal preferences work across projects; project exceptions retain a separate record and override only the corresponding personal default in that project. Temporary instructions are not durable memories. Model replies require valid structure and verbatim source evidence; the model and account allowlist have no fallback. Extraction and reconciliation each allow one format repair after a confirmed complete reply.

Reconciliation uses owner-scoped lexical/semantic candidates and a validated equivalent/supersedes/independent/ambiguous decision. Similarity never authorizes overwriting. Explicit, newer statements can supersede an active memory. Equivalents aggregate evidence; uncertain changes remain candidates. A source action is transactional and idempotent. Network calls happen outside SQLite locks. Already-forgotten or superseded equivalents are not automatically reactivated.

SQLite side tables store evidence, observed time, deadlines, relations and reversible changes. Existing main-table layouts and status values remain compatible with the previous runtime. Undo checks current versions and refuses to overwrite subsequent changes or forgotten records. Scope changes invalidate/rebuild vector projections, with canonical ownership checked before deletion.

Explicit absolute deadline dates use Asia/Shanghai; a date with no time includes that day through 23:59:59. Ambiguous deadlines are not inferred. Expired records stop normal recall and retain history. Only ordinary facts receive age-based ranking decay: 180-day half-life and a minimum multiplier of 0.8. Preferences, decisions and procedures do not expire by age.

## Interfaces

- POST /v1/sources accepts the original content string or messages [{id,role,content,observed_at}]. Message roles are user/assistant; observed_at accepts Unix seconds or ISO timestamps. The server bounds and validates envelopes before queueing.
- Memory responses add scope, observed_at, valid_until, topic, reason, evidence, relations, changes and effective_state. Existing fields remain.
- POST /v1/memories and PATCH /v1/memories/{id} accept optional valid_until (Unix seconds). PATCH additionally accepts project and still requires version. Empty project means personal.
- POST /v1/changes/{id}/undo reverses a change when its version guard permits.
- POST /v1/maintenance/cleanup queues reversible cleanup only for the authenticated user's existing memories. Overview reports progress. Ambiguous originals are preserved; uncertain provider requests stop that cleanup and are not blindly replayed.
- The five MCP tools retain their names and old parameters; remember/update accept optional valid_until. Device authentication and model/provider settings are unchanged.
- Export format self-agent-v2 includes evidence, metadata, relations and change history. Restore accepts v1/v2, remaps identifiers and never replaces newer local rows or resurrects forgotten records.

## Verification and rollout

87 automated tests and JavaScript syntax checks pass. The isolated real qwen3.8-max acceptance covers personal scope, equivalent merge with multiple sources, explicit replacement, project exception, temporary instruction and explicit deadline. Native prompts/replies and synthetic SQLite data remain in the private acceptance directory, outside Git. The public acceptance summary contains no user conversation or credentials.

Deploy with the existing off-host patch builder and checksum-verified no-build activator. Keep the previous release and SQLite snapshot. Additive side tables allow program rollback without dropping state; new lifecycle fields are only surfaced by the new runtime. Do not restore a pre-release database over newer user writes. Rollback temporarily suspends the new learning behavior.

Host Hook trust/reload remains a user action; standalone Hook/API/MCP checks are reported separately from an actual interactive host session and browser visual QA.
