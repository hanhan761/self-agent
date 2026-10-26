# Project workflow

- Store only program code and technical docs in Git. Keep credentials, personal conversations, databases and backups outside the repository.
- Preserve user and project isolation in every API, search, export and restore. SQLite owns authoritative content and lifecycle; search projections are rebuildable.
- All generative requests use the explicit native XJTU provider and account allowlist. No implicit provider, model or account fallback.
- Validate complete model outputs and source evidence. Assistant guesses are not user facts.
- Keep Windows unattended processes hidden; Python children use CREATE_NO_WINDOW.
- Preserve unrelated 4090 services, ports, credentials and workloads.
- Build releases off-host, verify checksums, and activate without installing or compiling dependencies on the target.
- Run meaningful service, privacy, lifecycle and restore tests. Report actual model and browser verification separately.
