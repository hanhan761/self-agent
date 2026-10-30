# Project workflow

- Store only program code and technical docs in Git. Keep credentials, personal conversations, databases and backups outside the repository.
- Preserve user and project isolation in every API, search, export and restore. SQLite owns authoritative content and lifecycle; search projections are rebuildable.
- All generative requests use the explicit native XJTU provider and account allowlist. Automatic model switching is allowed only within the explicitly configured native XJTU model pool on the same authorized account. No implicit provider/account fallback or model discovery outside that pool.
- Do not set generation output token caps; allow models to finish naturally. Transport timeouts and bounded response byte sizes are separate safeguards.
- Validate complete model outputs and source evidence. Assistant guesses are not user facts.
- Keep Windows unattended processes hidden; Python children use CREATE_NO_WINDOW.
- Preserve unrelated 4090 services, ports, credentials and workloads.
- Build releases off-host, verify checksums, and activate without installing or compiling dependencies on the target.
- Run meaningful service, privacy, lifecycle and restore tests. Report actual model and browser verification separately.
