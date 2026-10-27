# self-agent

![Self Agent：多设备与智能体共享一份持续积累的长期知识库](docs/assets/self-agent-hero.png)

在线入口：[self-agent.matterswarm.com](https://self-agent.matterswarm.com)，可直接用 CPA 中转站密钥登录，无需 Tailscale。安装步骤见 [接入说明](docs/access.md)。

个人智能体的长期知识库。一个私有网站和统一 API，让 Claude Code、Codex 与其他工具共享同一份可追溯的记忆。

- 搜索、记录、修订和停止调用记忆。
- 审核自动提炼的候选内容，保留原始资料与版本历史。
- 五个 MCP 工具、REST API、会话钩子和精选历史导入。
- 用户与项目隔离、独立客户端密钥、加密备份与合并恢复。

## Hook 与长期记忆的工作原理

Hook 是客户端在指定事件发生时自动调用的连接脚本。当前配置三类事件：模型处理前检索并补入相关记忆，本轮回复结束后采集新增对话，服务器再异步提炼和更新记忆。

![Self Agent Hook 原理图：会话开始和每次提问时检索记忆，回复结束后增量上传，后台提炼更新后供下一次检索](docs/assets/self-agent-hooks.png)

| Hook 事件 | 什么时候启动 | 做什么 |
| --- | --- | --- |
| SessionStart | 新会话开始或恢复时 | 检索个人偏好与当前项目记忆，补入历史参考 |
| UserPromptSubmit | 每次发送问题后、模型处理前 | 按本次问题检索相关记忆，补入模型上下文 |
| Stop | 本轮回复正常结束后 | 读取新增对话、脱敏并逐批上传；成功提交后才推进采集游标 |

正常完整对话中，新会话首轮通常触发 **3 次**，后续每轮通常 **2 次**；恢复、上下文压缩或中断会影响实际次数。后台提炼属于服务器队列任务，不是第四个 Hook，也不是每调用一次工具就触发一次。客户端需先完成 Hook 信任启用。

“越用越好用”来自有依据的记忆持续积累与修订：交晓智提炼、比较和校验新增信息，SQLite 保留原文依据、范围、状态与版本，检索时排除已失效的记忆，再把相关内容提供给下一轮模型。它不会训练或修改主模型参数；提炼异步完成，新信息可能在稍后才可检索。

[查看可编辑 SVG](docs/assets/self-agent-hooks.svg) · [图示生成脚本](ops/render_hook_diagram.py)

## 架构

网站、后台队列、SQLite 和可重建索引部署在服务器，客户端负责 MCP、会话采集和导入。

全部生成和提炼调用交晓智原生 HMAC API，不部署生成式大模型，不默认调用 OpenAI，不隐式更换账号或型号。可选 Mem0 / Qdrant 语义索引使用已缓存的多语向量模型（4090 当前使用 384 维 MiniLM；BGE-M3 可通过配置启用）；未准备好时，状态页明确显示关键词检索模式。

SQLite 管理权威内容、权限和生命周期。Mem0 使用 infer=False 写入已验证的记忆投影；交晓智提炼器独立校验结构、来源引文与用户角色，避免搜索组件覆盖来源或“忘记”状态。

## 开发与运行

需要 Python 3.11+；服务器发布包针对 Linux x86_64 / Python 3.12。

    python -m venv .venv
    .venv/Scripts/python -m pip install -e ".[test]"
    .venv/Scripts/python -m self_agent.cli init
    .venv/Scripts/python -m self_agent.cli serve

Windows 私有目录为 %LOCALAPPDATA%\self-agent，Linux 为 ~/.local/share/self-agent。init 只返回登录文件位置，不打印密码或密钥。通过 SELF_AGENT_DATA、SELF_AGENT_CONFIG 指定独立目录与配置。

    {
      "host": "127.0.0.1",
      "port": 8766,
      "xjtu_native_config": "/private/native-config.json",
      "xjtu_model": "qwen3.8-max",
      "allow_campus_http": true,
      "semantic": false
    }

原生配置引用受保护凭据并带 allowed_account_fingerprints。签名材料只在进程内读取。allow_campus_http 仅用于显式授权的校内入口。型号目录授权不等于完整生成可用，上线须分别验收。

## 智能体接入

推荐：在网站输入 CPA 密钥，点击“生成接入指令”，复制给当前 Codex / Claude Code，让智能体自动完成接入。已有客户端可运行 self-agent setup --client codex，隐藏输入密钥后自动配置；--client claude 或 both 可选择工具。详见 [接入说明](docs/access.md)。同一把 CPA 密钥对应同一个知识空间，请勿多人共用。

以下为高级手动配置方式：

在网站“智能体接入”创建密钥，写入仓库外的私有文件：

    self-agent connect --url http://<private-server>:8766 --token-file <private-token-file>
    self-agent install-client --client claude
    self-agent install-client --client codex

安装器保留现有设置并备份受影响配置。Codex 新钩子必须在产品 /hooks 界面完成信任审核；不会伪造信任或关闭检查。重启客户端后验证工具列表。

| MCP 工具 | 能力 |
| --- | --- |
| memory_search | 检索个人与当前项目知识 |
| memory_get | 查看内容及版本 |
| memory_remember | 记录明确事实、偏好、决策或流程 |
| memory_update | 按版本修订 |
| memory_forget | 停止调用，保留归档 |

项目身份来自规范化的 Git origin，与模型账号无关；无 Git origin 时使用本机路径摘要。钩子失败不阻塞主任务，成功提交后才推进采集游标。

## 备份与精选迁移

    self-agent inventory-local
    self-agent backup-local
    self-agent import-recent --project-dir <project-root> --days 30

备份只包含白名单中的会话 JSONL 与长期规则，不包含认证配置、.env 或密钥。原始会话使用流式 AES-GCM 加密，逐文件核验 SHA-256；密钥与归档分别保管。

历史导入只选择当前项目近 30 天的会话，以消息内记录的 cwd 判断归属；无归属或不相关会话会跳过并计数。采集会脱敏明显凭据，但不能保证识别所有秘密，请仅导入有权处理的资料。

网站支持 JSON 导出与合并恢复。CLI 支持密码加密：

    self-agent export knowledge.savault --password-file <private-password-file>
    self-agent restore knowledge.savault --password-file <private-password-file>

导出包含内容、来源和版本，不含登录密码、API 密钥或模型凭据。“忘记”表示停止检索，原文和审计仍保留，不代表永久擦除。

## REST API

除 /healthz 与静态网站外，数据接口需要登录 Cookie 或 Authorization Bearer 客户端密钥。

| 路径 | 方法 | 用途 |
| --- | --- | --- |
| /v1/search | GET | q、project、limit 检索 |
| /v1/memories | GET / POST | 列出、记录 |
| /v1/memories/{id} | GET / PATCH / DELETE | 查看、修订、停止调用 |
| /v1/sources | GET / POST | 原文与提炼队列 |
| /v1/sources/{id} | GET | 查看来源 |
| /v1/ask | POST | 根据知识调用交晓智回答 |
| /v1/export、/v1/restore | GET、POST | 导出与恢复 |

project 为空表示个人空间，项目检索包含个人记忆。列表省略 project 时可管理当前用户全部项目。数据始终绑定认证用户，客户端不能指定其他用户 ID。

## 验证与发布

    python -m pytest -q

tests/mcp_smoke.mjs 对独立测试账号实测 stdio 初始化、工具发现、写入与召回。详见 [部署说明](docs/deployment.md)。网站自托管于 4090，默认私有访问，不开放匿名注册。

公网 DNS、HTTPS、登录、密钥读写与 MCP 已验证。验收记录见 [public-acceptance.json](docs/public-acceptance.json)。
