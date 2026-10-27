# Install Self Agent local edition on this device

User-facing instruction: install the local Windows knowledge service and connect supported local Codex/Claude Code clients while preserving unrelated settings. Do not deploy or change a remote service.

1. Confirm Windows x64. Download the installer from the user's repository release:
   https://github.com/hanhan761/self-agent/releases/download/local-v0.2.1/Self-Agent-Local-0.2.1-0a578758354b-Setup.exe
2. Keep downloads and mutable state outside the Git checkout, preferably under %LOCALAPPDATA%/self-agent. Before executing the installer, verify SHA-256:
   4cf3b36f8dd7458f5117632b2ec74e2f3ba4fee94e2a413b2984aa7725d5f1f1
3. For an unattended agent install, run the installer with --extract-only <absolute-private-app-directory>. It validates the embedded archive and extracts the private Python/runtime/model. Run extracted pythonw.exe with source/scripts/setup_local.py and hidden console flags. Capture stdout/stderr into a private install log. Do not add keys or passwords to arguments, project files or URLs.
4. Read %LOCALAPPDATA%/self-agent/local/setup-result.json and require ok=true. The setup automatically reuses the selected local XJCode login, or opens the campus login window. A required human SSO/CAPTCHA step must be honestly reported, never bypassed. Missing WebView2 is prepared only when required.
5. Check the local status with extracted python.exe -m self_agent.cli status, using hidden execution. Verify only read operations in the user's real knowledge space; do not seed test preferences or synthetic notes there. Existing remote knowledge is exported, encrypted privately and restored before switching a prior remote client connection.
6. Setup backs up and merges only owned MCP and Hook entries, and adds a per-user background startup entry and optional Start Menu management shortcut. Repeated installs update the same knowledge directory. Do not rewrite the user's model selection, other tools, unrelated hooks or trust decisions.
7. Tell the user to start a new agent session. Codex must review/trust the new definitions via /hooks. Configuration, an independently exercised Hook subprocess and actual trusted host activation are different checks; report their real status separately. Never edit trust hashes or disable review to claim success.

No CPA key, pairing code, Tailscale, Docker, Node installation or local generative model is required. Knowledge retrieval stays local; native XJTU receives the redacted content needed for extraction. Current local storage is per device; this release does not provide multi-device synchronization.
