# Local Windows release build

The public installer is self-contained and installs under %LOCALAPPDATA%/self-agent/apps/<release>. Mutable knowledge, tokens, encrypted migration snapshots and runtime state remain outside the release in %LOCALAPPDATA%/self-agent/local. The process is per-user and does not require administrator elevation. Codex still requires hook review and a new session.

## Verified components

- CPython 3.13.17 official Windows x64 embeddable ZIP; SHA-256 9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38.
- All 76 runtime distributions pinned in requirements-local-windows.lock. The local SDK is mcp 1.30.0 to satisfy the upstream <2 constraint.
- onnx-community/paraphrase-multilingual-MiniLM-L12-v2-ONNX at revision d4c06bf0d7680171ac30042a1387e1fdb7a90021, full precision onnx/model.onnx, SHA-256 6fef515473041f6f40d7e5f630106e59ff50b22e1b1fccae39199b1d9f8ec03a. Copy tokenizer.json, tokenizer_config.json, config.json, special_tokens_map.json from that same revision. The installer contains the full model; no runtime model download is permitted.
- FlashRank 0.2.10 with Xenova/bge-reranker-base revision 280bcc27a84e0b898c251e06fddb25171bd9b101 (original BAAI model, MIT). INT8 model SHA-256 dd98f3e67837d23210a6b7550c08cced4f61845b940ac45be3565840a10f3244; tokenizer SHA-256 48564c5c7d3fa64d85d95e65414a542385f88b0f128fd8d4163fd7a57f2be05c. Place the five files and provenance.json from docs/reranker-model.json under runtime/models/rerank-bge/. Include BGE model license/notice and FlashRank license. The offline adapter fixes CPU/thread limits and calls upstream pairwise rerank, with no named-model downloads.
- Unmodified XJCode xjcode-login.exe, plus XJCode LICENSE and NOTICE. The helper handles only the user-visible campus login; credentials go over an owner-only named pipe to DPAPI storage.
- Microsoft official Evergreen WebView2 bootstrapper, downloaded from https://go.microsoft.com/fwlink/p/?LinkId=2124703. The build used a valid Microsoft Corporation Authenticode signature. Its exact bytes are pinned by the release manifest. It runs only when the documented registry check says the runtime is absent. See Microsoft's redistribution/runtime documentation.

## Prepare the runtime

Use a Windows build workspace outside private knowledge directories. Extract the verified Python ZIP into runtime/. Set python313._pth to these lines:

    python313.zip
    .
    Lib/site-packages
    source
    import site

Install the locked dependencies into runtime/Lib/site-packages with a matching Python, or cross-resolve binary wheels using --python-version 3.13 --platform win_amd64 --implementation cp --abi cp313 --only-binary=:all:. Build jieba 0.42.1 as a pure Python wheel separately and extract that wheel into the same site-packages directory.

Copy only self_agent/ and the five launcher scripts (hook_runner.py, mcp_runner.py, local_runner.py, setup_local.py, open_local.py) to runtime/source/. Place the model files under runtime/models/paraphrase-multilingual-MiniLM-L12-v2/. Place the login helper and optional WebView bootstrapper under runtime/bin/. Include vendor licenses under runtime/licenses/.

Run:

    python ops/build_local_bundle.py --runtime <prepared-runtime> --output dist/local

The builder rejects private data formats, whitelists runtime roots, hashes every file, emits manifest.json and SHA256SUMS.txt, and compiles a WinForms installer with the ZIP and its checksum embedded. No install/compile work runs on the 4090 server.

## Acceptance and rollout

Test the installer's --extract-only <new-private-directory> path, then run ops/verify_local_release.py against the extracted directory to verify every file. Run ops/accept_local.py with --source pointing at that extracted source, using a synthetic home/data profile. This is separate from merely testing repository code with an existing Python installation. Verify pythonw stdio using tests/mcp_smoke.mjs. ops/check_local_browser.py checks the actual one-use local browser login and desktop/mobile rendering.

Only after isolated acceptance, run the extracted setup on the real device. It first verifies local service readiness, encrypts and restores the current user's remote export when an existing remote connection is present, then switches owned client entries. It neither reads other users' exports nor modifies the remote service. Existing settings and the previous connection are kept privately for rollback. Do not package those private snapshots.

The WebView transport is covered by a real Windows named-pipe/DPAPI fixture test. A fresh campus SSO login and installation on a Windows machine lacking WebView2 have not been exercised unless separately recorded in local-acceptance.json. Avoid claiming a full clean-VM test from extracted-runtime acceptance.

The current-device maintenance update can overlay only verified changed release files at existing trusted command paths, with a canonical SQLite backup and old manifest/source backup, authenticated service shutdown and unchanged client/trust settings. A normal installation into a new release directory changes command paths and still requires host review/reload. Do not edit trust decisions to bypass that step.

Reproduce the isolated scale suite with the packaged Python and an explicit offline embedding directory:

    <runtime>/python.exe ops/benchmark_memory.py --output <new-private-benchmark-directory> --model-cache <runtime>/models/paraphrase-multilingual-MiniLM-L12-v2

The output directory must be new, outside Git, with room for synthetic SQLite corpora. The reranker sits beside the embedding directory at models/rerank-bge. No generative calls are made by this benchmark. Native lifecycle verification is reported separately.
