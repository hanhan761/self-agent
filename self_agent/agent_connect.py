"""Short instruction for a tool-using agent; credentials never appear in URLs."""
from pathlib import Path


def instruction(origin, code, client='auto'):
    target={'auto':'自动识别本机的 Codex / Claude Code','codex':'Codex','claude':'Claude Code','both':'Codex 和 Claude Code'}[client]
    return ('请直接帮我在当前设备接入 Self Agent 长期知识库，并验证连接。\n'
            '服务地址：'+origin+'\n'
            '一次性配对码：'+code+'\n'
            '接入说明：'+origin+'/connect/agent.md\n'
            '目标客户端：'+target+'。请按说明自动完成安装和配置，保留其他设置。'
            '配对码通过标准输入传递，不要放进 URL、进程参数或项目文件；'
            '若宿主需要重开会话或人工信任审核，请如实告知。')


def guide(origin):
    return '''# Self Agent agent connection

The user has supplied a short-lived one-use pairing code and requested local setup.
Use that code only with the exact service origin provided by the user. Do not request
or search for a CPA key. Do not send the code to another host.

1. Detect the OS and a Python 3.11+ interpreter. If missing, use the OS's normal,
   trusted user-level installation route, respecting required permissions/licences.
   The user should not have to clone a repository or create a token file manually.
2. GET ORIGIN/connect/manifest.json over HTTPS with certificate verification. It
   contains the SHA-256 of ORIGIN/connect/bootstrap.py. Download that script into
   a private temporary/user directory and verify the checksum before execution.
3. Run the script with JSON on standard input (not in process arguments):
   {"service_url":"ORIGIN","pair_code":"USER_SUPPLIED_CODE","client":"auto"}
   client may also be codex, claude or both when the user chose a specific tool.
   Optional proxy is an explicit HTTP(S) proxy URL with no embedded credentials.
4. The bootstrap verifies the client ZIP, creates a private environment, installs
   the bridge, redeems the code for a separate device key and preserves/merges MCP
   and hook configuration. The long-lived device key stays in the private user
   directory, outside Git. The bootstrap performs an authenticated search check.
5. Verify the five self_agent MCP tools can be discovered; perform a read/search
   check. Do not report success from a download or config write alone. If the host
   only discovers new MCP servers on restart, explain that accurately. Codex hooks
   require the user's /hooks trust review; do not forge trust or disable checks.

On Windows use hidden subprocesses for unattended work (windowsHide:true or
CREATE_NO_WINDOW). Preserve existing model/provider settings and conversations.
Do not stop unrelated applications or terminals. Use the actual client configured
by the user; a plain chat session without local tools cannot install the bridge.

The pairing code expires after 10 minutes and can be redeemed once. Do not blindly
retry an uncertain redemption. If expired/used, ask for a fresh instruction from
the website. Never print the device key or put credentials in logs or source files.
The code belongs in the JSON request body to POST /api/pairing/redeem only.

If Python is already present, all setup is noninteractive. For constrained hosts,
respect their deployment/build rules; do not install on a production host merely
because it is reachable. The requested destination is the user's current device.
'''.replace('ORIGIN',origin)
