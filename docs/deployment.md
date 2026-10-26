# 4090 统一网站与 API

## 拓扑

- 目标为 yun 登记的 workstation，连接保留 PEM、登记表与主机指纹校验。
- 项目根为 /home/codex-admin/services/self-agent。
- releases/<revision> 保存不可变程序与开发机准备好的依赖，current 指向当前版本。
- state 保存数据库和运行记录，权限 0700；config/server.json 保存配置和凭据引用，权限 0600。
- 独立服务为 self-agent.service。
- 当前入口为 https://self-agent.matterswarm.com；Cloudflare Tunnel 转发到 127.0.0.1:8766。

用户侧无需 Tailnet。公网使用 HTTPS，网页登录 Cookie 启用 Secure/HttpOnly/SameSite，设备 API 使用独立 Bearer 密钥。SSH 运维仍使用已登记连接。原私有 HTTP 入口已停止监听；本次仅新增授权域名的隧道路由。

## 资源

生成与提炼全部使用交晓智，不下载生成模型，不占用现有 GPU 推理任务。语义索引只使用已缓存向量模型，默认 CPU。

界面是纯静态文件，Python 依赖在开发机准备为 Linux wheels。服务器不运行 pip、npm、编译器或构建工具。

小型服务项目预算限制发布包、展开体积、数据与内存，并按真实需求预检，保留 100 GiB 磁盘余量。此策略依据本次轻量安装要求制定，区别于 yun 未指定项目容量时的默认 15% 余量线，不能扩展为安装生成模型或清理其他项目。

## 发布与回滚

1. 开发机运行检查，记录精确源提交。
2. 准备 Linux / Python 3.12 wheels；Jieba 通用 wheel 在开发机生成。
3. python ops/build_release.py --revision <commit> 生成逐文件哈希与不可变包。
4. 通过 scripts/yun_hidden.py 核验目标、磁盘、端口与压力。
5. 有界上传到 incoming，bootstrap 仅通过私有文件传递，不进入源码或参数。
6. ops/activate.py 在锁内校验、离线导入检查并无构建激活。
7. 验证进程、origin、客户端、鉴权及原生完整回复，观察至少 60 秒。

Windows 控制器仅改变本项目的隐藏进程启动方式，不改全局 yun 代码或身份验证。

首装回滚：

    sudo systemctl disable --now self-agent.service

数据库与备份保留。更新时保留前一 release，回退 current 后重启本服务。涉及数据格式变化时须先验证兼容性，不可盲目回退。

## 验收边界

- healthz 不代替客户端、鉴权或模型验收。
- pending、failed、uncertain 不算提炼成功。
- 状态页未启用语义索引时，不声称完成语义召回。
- CUA 没有浏览器时，记录视觉验收未完成，不以 API 检查替代。

## 当前验收

程序版本为 0874a65774ad24be49cea64b8083fccf88508dfd。机器可读验收记录见 [acceptance.json](acceptance.json)。53 项测试通过；真实 MCP、原生交晓智、加密导出恢复均已验证。关键词 Top5 为 30/30，同义改写为 9/10，不能据此保证一般查询准确率。

依赖更新使用完整包；仅源码修复可在开发机运行 ops/build_patch.py，指定已验证基础版本。激活器检查完整继承文件清单，在独立 release 中硬链接未变文件、替换改动文件，再原子切换；不会原地修改旧版本。

## 公网切换完成

2026-10-26 已验证新域名、TLS、匿名数据请求 401、网页登录、密钥读写和 MCP。运行时仍为 78e83d3367b2，公网配置备份位于 /home/codex-admin/services/self-agent/config/public-rollouts/1793014327186777232-self-agent.matterswarm.com。回滚时在项目发布锁内恢复该目录的 server.before.json 和 tunnel.before.yml 到各自原路径，保持原属主和权限，再重启 self-agent 与 cloudflared；恢复前检查原域名路由及私有入口是否仍适用。客户端 URL 需相应恢复。没有数据格式迁移。

## CPA 联合认证与设备接入

部署器 --cpa-auth 为本项目启用只读 CPA 注册表路径，不修改 CPA 服务。新增身份、会话绑定、设备绑定与一次性配对表均为增量表；旧程序可继续读取原有数据。认证缓存依据源文件 inode/mtime/size 刷新，文件异常时拒绝 CPA 认证，原账号仍可恢复。

客户端公开源码包由 ops/build_client.py 在开发机生成，包含白名单程序文件与 SHA-256 清单；发布脚本自动包含它。服务器只生成带短期配对码的小型用户接入 ZIP，不在服务器构建程序、安装依赖或复制 CPA 原始密钥。

CPA 本次更新回滚程序时，必须同时恢复 config/backups/before-c4f7a42b2aa2.json 到 config/server.json，再切回 releases/78e83d3367b2 并重启 self-agent。该备份已与更新前公网配置的 SHA-256 对齐，并用旧程序验证可读取；不能只切换程序指针而保留旧程序不识别的 CPA 配置字段。
