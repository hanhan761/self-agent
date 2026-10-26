# Implementation plan

1. Repository initialization and first push — complete.
2. Central 4090 API, website, native XJTU provider, memory lifecycle — in progress.
3. MCP, client hooks and allowlisted backup/import — pending.
4. Tests, browser verification, reproducible release and final push — pending.
5. Deployment — gated: root filesystem has 111 GiB free, below yun 15% reserve; asked for an alternative mounted data disk. No production mutation performed.

Scope: private authenticated website and central API on 4090. Stable user identities and separate project scope. Local controller handles client hooks/import. Secrets and data remain outside Git.
