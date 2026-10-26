# 接入与设备互联

公网入口为 https://self-agent.matterswarm.com，DNS、TLS、登录、密钥读写与 MCP 已实测通过。客户端只需要服务地址和自己账号的设备密钥，不需要 Tailscale；手机可以直接浏览器登录。

## Windows 客户端

安装 Git 和 Python 3.11，然后在自选目录执行：

    git clone https://github.com/hanhan761/self-agent.git
    cd self-agent
    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e .

管理员为新使用者创建独立账号。登录网站，在“智能体接入”为每台设备创建独立密钥，保存在仓库外的私有文本文件。不要共用管理员账号，不要把密钥写进 Git。

    .\.venv\Scripts\python.exe -m self_agent.cli connect --url https://self-agent.matterswarm.com --token-file <私有密钥文件绝对路径>
    .\.venv\Scripts\python.exe -m self_agent.cli install-client --client claude
    .\.venv\Scripts\python.exe -m self_agent.cli install-client --client codex

选择实际使用的客户端安装。原配置会备份并合并。重启客户端；Codex 需在 /hooks 审核信任。保留安装目录和虚拟环境。

每台设备通过 HTTPS 访问同一服务。一个用户的设备共享其个人及项目记忆；不同用户的数据隔离。相同 Git origin 对应相同项目，但不自动跨用户共享。设备离线时不提供本地知识库副本。

生成请求由 4090 调用交晓智；客户端不需要交晓智凭据或 GPU。手机浏览器可管理和查询资料，当前不会自动读取手机微信。

## 本次公网发布

使用 4090 已有的 Cloudflare Tunnel；新路由只指向本机 127.0.0.1:8766。网页登录使用 Secure/HttpOnly Cookie，API 使用 Authorization: Bearer 设备密钥。未登录的数据请求返回 401，不开放匿名注册。

DNS 记录：CNAME self-agent.matterswarm.com -> caa74e4b-9f75-40d1-822a-77a32d993b77.cfargotunnel.com，开启代理。此前该记录不存在。DNS 由账号持有人在控制台添加，不索取其 API Token。

ops/public_access.py 默认只生成候选配置并校验，显式 --apply --confirm-name <相同域名> 才切换。切换前备份两个配置，持有项目发布锁，保留全部既有路由；异常时恢复配置和服务。回滚目录由执行输出记录。公网是否完成，以独立的 DNS、TLS、匿名拒绝、登录和密钥读写验收为准。

若所在网络需要代理，可以在 connect 命令末尾显式指定 --proxy http://127.0.0.1:<本机代理端口>。普通网络不需要此参数。客户端保持 HTTPS 证书校验，不自动读取未知环境代理。当前控制机校园 DNS 对新域名仍返回旧的 NXDOMAIN，已使用其现有网络代理连接；公共 DNS 与公网 HTTPS 均已验证。
