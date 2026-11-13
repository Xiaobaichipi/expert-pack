# wechat-bridge — 给 DSH 用的「微信发消息」最小 MCP 服务器

DeepSeek Harness 本身没有微信插件，但内置 MCP 客户端（`@deepseek-ai/dsh-mcp-client`）。
这个小服务把「往微信推送消息」包装成 MCP 工具，让 agent 直接调用，不需要装微信、不碰微信客户端、
不改 DSH 源码。

- **零依赖**：只用 Python 标准库，内网/离线可用。
- **三条通道**（都是官方接口，不存在封号风险）：

| 工具 | 通道 | 收消息的人 | 前置条件 |
|---|---|---|---|
| `wechat_push` | [Server酱 Turbo](https://sct.ftqq.com) | 你自己的个人微信（服务号） | 微信扫码登录拿 `SendKey`（免费 5 条/天） |
| `wecom_app_send` | 企业微信自建应用 | 企业成员（在「微信插件」里用个人微信收） | 企业 ID + 应用 Secret + AgentId |
| `wecom_robot_push` | 企业微信**群机器人** webhook | 群成员（微信插件里也能看到） | 一个 webhook 地址 |

> 三者都是**单向推送**（agent → 微信）。要「读微信消息再回」需要微信客户端自动化，见
> 工作区根目录的《微信接入方案调研.md》。

## 1. 拿凭据

### A. Server酱（最省事，适合给自己发通知）

1. 打开 <https://sct.ftqq.com>，用微信扫码登录；
2. 进入「SendKey」页面复制，形如 `SCT123456T...`；
3. 免费会员每天 5 条，会员额度见[文档](https://sct.ftqq.com/docs/getting-started/faq/)。

### B. 企业微信自建应用（适合发给公司同事）

1. 注册企业微信 → 「我的企业」底部复制**企业 ID**（`ww...`）；
2. 「应用管理 → 自建 → 创建应用」，进应用详情复制 **AgentId** 和 **Secret**；
3. 「我的企业 → 微信插件」扫码关注，成员才能在个人微信里收到应用消息；
   若收不到，勾选「允许成员在微信插件中接收和回复聊天消息」，并关闭客户端的「仅在企业微信中接收消息」。

> 注意：`appchat/send`（群聊接口）推的消息**微信插件收不到**，应用消息和群机器人 webhook 可以。

### C. 群机器人 webhook

企业微信群 → 右上角「群机器人 → 添加」→ 复制 webhook 地址（含 `key=`）。

## 2. 接到 DSH

编辑当前 profile 的补丁层（Windows 默认
`C:\Users\11454\.dsh\profiles\desktop\cordis.patch.yml`），在末尾追加一条：

```yaml
- id: mcp-wechat-push
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: wechat            # 工具会变成 mcp__wechat__wechat_push 等
    transport: stdio
    command: 'C:\Users\11454\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
    args: ['F:\work\2026年\10月\专家包\wechat-bridge\mcp_server.py']
    env:
      SCT_SENDKEY: SCT换成你自己的key
      WECOM_CORP_ID: ww换成你的企业id
      WECOM_AGENT_ID: '1000002'
      WECOM_SECRET: 换成你的应用Secret
      WECOM_ROBOT_URL: https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=换成你的key
```

保存后 DSH 会重载配置；新会话里应该能看到
`mcp__wechat__wechat_push`、`mcp__wechat__wecom_app_send`、`mcp__wechat__wecom_robot_push` 三个工具。

> 凭据也可以不写进 yaml，改成 `!!js process.env.SCT_SENDKEY` 从环境变量取。
> DSH 拉起子进程时会把父进程里名字含 `KEY/SECRET/TOKEN/PASSWORD` 和 `DSH_*` 的变量清掉，
> 所以**必须**在 `env:` 里显式给，靠父进程环境变量是传不进去的。

只想发给自己、不介意每天 5 条，就只配 `SCT_SENDKEY` 一行即可。

## 3. 本地自测

```powershell
$py = 'C:\Users\11454\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .\mcp_server.py --selftest   # 协议冒烟测试
& $py .\test_protocol.py           # 真起子进程跑完整 JSON-RPC 握手（10 项断言）
```

想验证凭据是否可用，直接在配置好后对 agent 说：
「用 mcp__wechat__wechat_push 发一条测试消息，标题=测试，正文=打通了」。

## 4. 安全提醒

- `mcp_server.py` 只做「发」，不读任何本地数据；没有 shell、没有文件读写。
- SendKey / Secret 等于发送权限，别提交进 git，别贴进会话。
- 群机器人 webhook 泄露后任何人都能往群里发消息，泄露了就在群里重置。
