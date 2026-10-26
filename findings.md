# Findings

- Initial folder has no source; Git exists outside PATH.
- Claude Code 2.1.154 and Codex CLI 0.163.0 are installed.
- Native XJTU HMAC adapter is available in the local skill; only TCP connectivity was verified. No project credential source has been provided.
- Mem0 exposes a custom LLM registration interface; Chinese search requires local multilingual embeddings.
- Codex hooks require product trust review.

- User changed deployment to the authorized 4090 (workstation): central API and website, with local client adapters.
- First Git push via PowerShell returned no output; direct remote verification failed to reach github.com. Treat push as unverified, not successful.

- Deployment is now explicitly a small website/API only, not a generative model host; all generation uses XJTU. Existing BGE cache may be reused without downloading weights. User questioned large-model deployment; clarified this boundary.
