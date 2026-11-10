---
name: pms-gateway-mcp
slug: pms-gateway-mcp
displayName: PMS 接口网关（变电问数底座）
description: >-
  变电智能问数 PMS 接口网关底座：把国网河南院电网资源业务中台（PMS）服务目录中筛出的 26 个变电专业优先接口，
  统一封装成 MCP（stdio）/ CLI / Python 三轨可用的工具集，覆盖设备台账（资产ID/资源ID/实物ID、设备参数、电网设备列表）、
  设备树导航（根节点、逐层下钻）、运维健康（缺陷、隐患、故障/跳闸记录）、检修试验（检修计划、检修方案、修试记录、巡视计划、巡视记录、检测试验项目）、
  可靠性分析（变电站可靠率、中压停电事件、设备可开放容量）、作业资源与图形拓扑（智能装备、仪器仪表、生产厂家、专题图 SVG、电源点供电路径、供电范围/停电影响）。
  触发词：PMS 接口、中台接口、变电问数取数、设备台账、设备台账详情、资产ID、资源ID、实物ID、设备树、缺陷查询、隐患查询、故障记录、跳闸记录、
  检修计划、检修方案、修试记录、巡视计划、巡视记录、试验项目、可靠性、供电可靠率、停电事件、停电影响、可开放容量、负载率、智能装备、在线监测、
  机器人、仪器仪表、生产厂家、专题图、接线图、电源点、供电路径、供电范围、Mock 联调、鉴权切换、MCP 工具挂载。
  也适用于用户明确要求调用「pms-gateway-mcp / PMS 接口网关 / 变电接口底座」。
version: 1.1.0
metadata:
  author: 国网河南院 变电智能问数项目组
  package_type: skill
  display_name: PMS 接口网关（变电问数底座）
  category: data-gateway
  tags:
    - pms
    - mcp
    - 变电问数
    - 设备台账
    - 缺陷隐患
    - 检修试验
    - 可靠性
    - 图形拓扑
    - mock
compatibility: 纯 Python 3.10+ 标准库；MCP 协议 2024-11-05（stdio、换行分隔 JSON-RPC 2.0）
---

# PMS 接口网关（变电智能问数底座）

**角色**：接口网关工程师。你负责把 26 个 PMS 接口**准确、可追溯地**调用起来，并把返回值归一给上层问数专家；
不负责编造业务结论，不绕过网关直连数据库，不把任何凭证写进代码。

## 何时使用本技能

- 需要取变电业务数据（设备台账 / 缺陷隐患 / 检修试验 / 可靠性 / 资源与拓扑）而**手里只有自然语言问题**时；
- 需要确认「有没有对应接口、参数怎么传、返回什么字段」时（先 `describe`，再 `call`）；
- 需要给宿主挂载 MCP 工具、或写脚本批量取数时；
- 需要联调鉴权（mock → 真实网关）与排查取数失败原因时。

上层业务问题请交给 `substation-asset-ledger`、`substation-om-health`、`substation-maintenance-test`、
`substation-reliability`、`substation-resource-topology`、`substation-device-tree` 等领域技能，
由 `substation-qa-orchestrator` 统一编排；本技能只保证「接口调用与数据返回」正确。

## 一、能力清单（6 组 / 26 个工具）

| 分组 | 工具 |
|---|---|
| 设备台账（5） | `get_asset_by_id`、`list_asset_params`、`get_device_by_utc_num`、`list_psr_by_filters`、`get_psr_by_id` |
| 设备树导航（2） | `get_device_tree_root`、`get_device_tree_nodes` |
| 运维健康（4） | `inquire_defect`、`view_defect`、`list_hazard`、`list_fault_trip_records` |
| 检修试验（6） | `get_repair_plan`、`find_repair_test`、`find_repair_program`、`list_patrol_plan`、`list_patrol_record`、`list_test_item` |
| 可靠性分析（3） | `query_station_scale_analysis`、`query_outage_incident`、`query_open_capacity` |
| 资源与拓扑（6） | `find_smart_device`、`get_instrument_list`、`get_manufacturer_infos`、`query_svg_map_by_psr_id`、`search_power_path`、`analyze_supply_area` |

完整的接口编码、地址、入参、返回形态、典型问数见 [`references/interfaces.md`](references/interfaces.md)。
工具定义（名称/参数/required/mock）的唯一事实源是专家包中的 `spec/interfaces.json`，**改接口只改 spec**。

## 二、环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `PMS_AUTH_MODE` | `mock` | `mock` / `none` / `appkey` / `token` |
| `PMS_GATEWAY_BASE_URL` | 空 | 网关完整地址；非 mock 模式必填 |
| `PMS_APP_KEY` / `PMS_APP_SECRET` | 空 | appkey 模式凭证，**禁止硬编码** |
| `PMS_TOKEN` | 空 | token 模式访问令牌 |
| `PMS_TIMEOUT` | `30` | 单次请求超时（秒） |
| `PMS_RETRY` | `1` | 重试次数（仅网络/超时/429/5xx） |
| `PMS_SPEC_PATH` | 自动定位 | 可选；发布 zip 已内置 spec 快照（`references/interfaces.json`），一般无需设置，仅用于覆盖内置快照或本地调试 |
| `PMS_VERIFY_SSL` | `1` | `0` 关闭证书校验（仅测试环境） |

本地模拟网关（`pms_cli.py mock-server`，二期新增）另有 6 个**服务端**变量，只影响本地 mock：
`PMS_MOCK_TOKEN`（默认 `mock-token-001`）、`PMS_MOCK_APP_KEY`（`mock-app-key`）、
`PMS_MOCK_APP_SECRET`（`mock-app-secret`）、`PMS_MOCK_TIME_WINDOW`（`300` 秒）、
`PMS_MOCK_HOST` / `PMS_MOCK_PORT`（`127.0.0.1` / `18080`）。默认值均为公开模拟凭证，**仅本地联调**。

鉴权细节与凭证申请流程见 [`references/auth.md`](references/auth.md)；appkey 的**模拟签名规范**
（客户端与本地模拟网关共用同一实现）见 [`docs/09-模拟网关与鉴权.md`](../../docs/09-模拟网关与鉴权.md)。

## 三、四种用法

### 3.1 MCP 宿主挂载（推荐）

宿主以 stdio 方式拉起脚本即可，**无需 PYTHONPATH**（脚本自行处理导入路径）：

```json
{
  "mcpServers": {
    "pms-gateway-mcp": {
      "command": "<你的 python.exe 绝对路径>",
      "args": ["<专家包绝对路径>/skills/pms-gateway-mcp/scripts/mcp_server.py"],
      "env": {
        "PMS_AUTH_MODE": "mock"
      }
    }
  }
}
```

等价启动方式：`python scripts/pms_cli.py serve`。
协议能力：`initialize`（protocolVersion `2024-11-05`、`capabilities.tools={}`）、`notifications/initialized`、
`ping`、`tools/list`（26 个工具，含 inputSchema）、`tools/call`（`content:[{type:"text",text:<JSON>}]` + `isError`）。
**stdout 只走协议消息，日志一律 stderr**；单条消息解析失败只回 `-32700`，进程不退出。

### 3.2 CLI

```bash
python scripts/pms_cli.py doctor                         # 环境/配置/spec/26 个 mock 工具自检
python scripts/pms_cli.py list-tools                     # 26 个工具全览
python scripts/pms_cli.py list-tools --group om-health   # 按分组过滤
python scripts/pms_cli.py describe get_asset_by_id       # 单工具入参/返回/示例
python scripts/pms_cli.py call get_asset_by_id --params '{"assetId":"AST-102-0001"}'
python scripts/pms_cli.py call inquire_defect --params '{"defectLevel":"严重"}' --with-items
python scripts/pms_cli.py serve                          # 以 CLI 方式启 MCP stdio 服务
```

退出码：`0` 成功；`1` 运行时错误（PmsError，错误 JSON 写 stderr）；`2` 参数/用法错误。
输出统一为 UTF-8 JSON（`ensure_ascii=False`）。

### 3.3 Python 调用

```python
import sys
sys.path.insert(0, "<专家包>/skills/pms-gateway-mcp/scripts")
from pms_client import PmsClient

client = PmsClient()                                     # 默认 mock
resp = client.call_tool("get_asset_by_id", {"assetId": "AST-102-0001"})
# 或使用同名显式方法（26 个工具都有）
resp = client.get_asset_by_id("AST-102-0001")
print(resp["data"]["assetName"])

# 列表/分页：extract_list / extract_total 兼容 data.list / data.records / 直接 list
from pms_client import extract_list, extract_total
resp = client.list_psr_by_filters(deviceType="变压器", pageSize=10)
items, total = extract_list(resp), extract_total(resp)
```

### 3.4 本地模拟网关（mock-server，二期新增）

需要**走真实 HTTP + 鉴权链路**（而不是 mock 直出）时，用模拟网关：

```bash
# 终端 1：启动网关（阻塞运行，Ctrl+C 退出；监听地址与客户端对接提示打印到 stderr）
python scripts/pms_cli.py mock-server --host 127.0.0.1 --port 18080 --auth-mode token
# 可选：--auth-mode appkey（HMAC 签名）/ none（免鉴权）；--port 0 自动分配空闲端口；--verbose 逐请求打日志

# 终端 2：客户端指向网关
#   PowerShell:
#     $env:PMS_GATEWAY_BASE_URL = "http://127.0.0.1:18080"
#     $env:PMS_AUTH_MODE        = "token"
#     $env:PMS_TOKEN            = "mock-token-001"
#     $env:PMS_RETRY            = "0"
python scripts/pms_cli.py doctor
python scripts/pms_cli.py call get_asset_by_id --params '{"assetId":"AST-102-0001"}'
```

- 网关按 `spec/interfaces.json` 动态注册 **26 条路由**，返回 `{"code":0,"message":"ok","data":…,"meta":…}`；
  列表接口 `data={"list":[…],"total":N,"pageNo":p,"pageSize":s}`；未知路由 404、方法不符 405、
  鉴权失败 401/403，均为 JSON（客户端归一为 `AUTH_FAILED`）。
- appkey 模式：客户端需 `PMS_APP_KEY=mock-app-key` + `PMS_APP_SECRET=mock-app-secret`；
  签名 = `HMAC-SHA256(secret, appKey\nget/post大写\npath\ncanonical_query\nsha256(body)\ntimestamp\nnonce)`
  小写 hex，服务端校验 ±300s 时间窗 + nonce 防重放（重放 403）。
- 进程内（单测/脚本）更简单：`start_server("127.0.0.1", 0, "token")` 返回对象含
  `base_url` / `routes` / `dispatch()` / `stop()`，端口 0 自动分配，`server.dispatch(...)`
  可完全绕开 socket 验证路由与鉴权。
- 完整规范（签名逐字节说明、26 接口数据说明、环境变量、限制）见
  [`docs/09-模拟网关与鉴权.md`](../../docs/09-模拟网关与鉴权.md)。

## 四、返回结构与分页、过滤

- 统一返回 `{code, message, data}`；`code=0` 成功。真实模式附加 `meta`（工具名/接口编码/鉴权模式）。
- mock 模式 `message` 明确标注「mock 数据（内置样例，仅用于联调…）」，`meta.mode="mock"`，
  回答用户时**必须**注明「Mock 数据，仅用于联调」。
- 走本地模拟网关（`PMS_AUTH_MODE=token|appkey` + `PMS_GATEWAY_BASE_URL`）时返回
  `{"code":0,"message":"ok","data":…,"meta":{tool,interfaceCode,method,path,paged,authMode,server:"mock-gateway"}}`；
  数据仍是虚构模拟数据，回答时同样要注明「模拟数据」。
- 列表提取兼容 `data.list` / `data.records` / `data.rows` / 直接数组；总数兼容 `total` / `totalCount` / `count`。
- 分页参数 `pageNo`（从 1 开始）/ `pageSize`；mock 模式支持按样例字段做**等值/包含**过滤
  （如 `deviceType=变压器`、`name=断路器`、`onlineStatus=在线`），并返回过滤后的 `total`。
- 参数严格校验：多余参数、缺少必填、类型不符都会报 `INVALID_PARAM`（MCP 层为 `-32602`）。

## 五、鉴权模式

| 模式 | 用途 | 状态 |
|---|---|---|
| `mock` | 无凭证联调 / 演示 / 单测（默认） | ✅ 开箱可用 |
| `none` | 网关侧免鉴权或代理统一鉴权 | ✅ 配好 `PMS_GATEWAY_BASE_URL` 即可 |
| `token` | Bearer Token（`Authorization`） | ✅ 填 `PMS_TOKEN` 即可（本地模拟网关默认期望 `mock-token-001`） |
| `appkey` | appKey + 时间戳 + nonce + HMAC 签名 | ✅ 已实现二期「模拟规范」（`pms_client/signing.py`，客户端与模拟网关共用；真实中台规范下发后只替换该实现） |

## 六、错误码

| 错误码 | 含义 | 处理建议 |
|---|---|---|
| `UNKNOWN_TOOL` | 工具名不存在 | `tools/list` / `list-tools` 查看可用工具（会给出近似建议） |
| `INVALID_PARAM` | 参数缺失/多余/类型不符 | `describe <tool>` 核对入参与 required |
| `NOT_CONFIGURED` | 非 mock 模式配置缺失 | 补 `PMS_GATEWAY_BASE_URL` / 凭证，或先切回 mock |
| `AUTH_MODE_INVALID` | 鉴权模式非法 | 改为 `mock`/`none`/`appkey`/`token` |
| `AUTH_MISSING_CREDENTIALS` | 凭证为空 | 配 `PMS_TOKEN` 或 `PMS_APP_KEY`+`PMS_APP_SECRET` |
| `AUTH_SIGNATURE_TODO` | 历史错误码：appkey 签名未实现 | 二期已实现签名（`pms_client/signing.py`），**不再抛出**；仍保留常量用于兼容旧日志 |
| `AUTH_FAILED` | HTTP 401/403（凭证/签名/时间窗/nonce 重放） | 核对模式与凭证；连模拟网关时检查是否与 `PMS_MOCK_TOKEN` / `PMS_MOCK_APP_KEY`+`PMS_MOCK_APP_SECRET` 一致、时间戳是否在 ±300s 内、nonce 是否重复 |
| `SPEC_NOT_FOUND` / `SPEC_ERROR` | spec 缺失或非法 | 发布 zip 已内置 `references/interfaces.json`；若被删/损坏，设 `PMS_SPEC_PATH` 或 `--spec` 指向有效 spec |
| `TIMEOUT` / `NETWORK` | 超时 / 网络不可达（可重试） | 增大 `PMS_TIMEOUT`、检查网络与网关地址 |
| `RATE_LIMITED` | HTTP 429 限流（可重试） | 降频、增大重试间隔、申请 QPS 配额 |
| `SERVER_ERROR` | HTTP 5xx（可重试） | 稍后重试；持续失败联系中台运维 |
| `PARSE_ERROR` | 返回非 JSON | 抓包核对返回体与接口契约 |
| `REMOTE_ERROR` | 网关业务码非 0 | 依据 message / 远端 code 修参数或权限 |
| `MOCK_ERROR` | 某工具缺 mock 数据 | 补 spec 的 `mock` 字段 |

MCP 协议错误：`-32700` 解析失败、`-32600` 非法请求、`-32601` 未知方法、`-32602` 参数错误、`-32603` 内部错误。

## 七、故障排查

| 现象 | 排查步骤 |
|---|---|
| `tools/list` 没有 26 个工具 | 1) `pms_cli.py doctor` 看 `spec.toolCount`；2) 确认内置快照或 `PMS_SPEC_PATH` / `--spec` 未指向旧文件；3) 看 stderr 的启动日志（含 spec 路径与工具数） |
| `SPEC_NOT_FOUND` | 发布 zip 应内置 `references/interfaces.json`；若被删/损坏，设 `PMS_SPEC_PATH` 指向最新 spec |
| MCP 宿主连不上 / 无响应 | 1) 确认命令与参数路径正确、python 可执行；2) 确认 **stdout 没有非协议输出**（日志只应出现在 stderr）；3) 手工 `echo` 一行 `initialize` 验证握手；4) 查看宿主日志里的 stderr |
| 返回 `-32602` | 用 `describe <tool>` 对照 required 与类型；参数名必须与 spec 完全一致（大小写敏感） |
| 真实模式 401/403 | 检查模式与凭证是否匹配、令牌是否过期、网关环境（测试/生产）是否正确；连模拟网关时核对是否与 `PMS_MOCK_TOKEN` / `PMS_MOCK_APP_KEY`+`PMS_MOCK_APP_SECRET` 一致 |
| 真实模式 `NOT_CONFIGURED` | `PMS_GATEWAY_BASE_URL` 为空或不是 `http(s)://` 开头；联调期可 `PMS_AUTH_MODE=mock`，或指向本地 `mock-server` |
| 中文乱码 / `UnicodeEncodeError` | CLI 与 MCP 启动时已把 stdio 重配为 UTF-8；Windows 控制台可 `chcp 65001` 或设 `PYTHONUTF8=1` |
| 超时、慢 | 调大 `PMS_TIMEOUT`；确认可重试错误（`TIMEOUT`/`NETWORK`/`RATE_LIMITED`/`SERVER_ERROR`）已配置 `PMS_RETRY`；本地回环联调建议 `PMS_RETRY=0` |
| mock-server 启动即报「端口被占用」 | 换 `--port`（或 `--port 0` 自动分配）；先确认同端口没有别的进程（`Get-NetTCPConnection -LocalPort 18080`） |
| mock-server 返回 404 | 路径/方法必须与 `spec/interfaces.json` 完全一致（26 条路由按 spec 注册）；`GET` 打 POST 路由会得到 405 |
| appkey 返回「时间戳超出允许窗口」 | 本机与网关需对时；时间窗默认 ±300s，可用 `PMS_MOCK_TIME_WINDOW` 调整；伪造的旧时间戳会被拒 |
| appkey 返回「nonce 已被使用」 | 每次请求必须生成新的 `X-PMS-Nonce`（客户端自动生成；手工脚本/压测复用一个 nonce 会触发 403 防重放） |
| mock 过滤后查不到数据 | mock 只对样例里真实存在的字段过滤；`stationId` 等样例中不存在的字段会被忽略（不报错、不误杀） |

## 八、目录结构与本技能的维护

```
skills/pms-gateway-mcp/
├── SKILL.md                     # 本文件
├── references/
│   ├── interfaces.md            # 26 工具目录表 + 典型问数 + 返回/分页/主键约定
│   └── auth.md                  # 四种鉴权模式、环境变量、凭证申请流程（签名实现以 pms_client/signing.py 为准）
└── scripts/
    ├── mcp_server.py            # MCP stdio 服务（JSON-RPC 2.0，换行分隔）
    ├── pms_cli.py               # CLI：list-tools / describe / call / serve / doctor / mock-server
    ├── mock_gateway/            # 二期：本地可鉴权模拟网关
    │   ├── data.py              # 26 接口确定性模拟数据（虚构、主键一致、分页/过滤）
    │   ├── auth.py              # token / appkey（±300s 时间窗、nonce 防重放）/ none
    │   └── server.py            # ThreadingHTTPServer + 按 spec 注册 26 条路由
    └── pms_client/
        ├── config.py            # 环境变量 → PmsConfig；spec 自动定位
        ├── auth.py              # AuthProvider + mock/none/appkey/token；签名委托 signing.py
        ├── signing.py           # 二期：appkey 签名规范唯一实现（客户端与服务端共用）
        ├── errors.py            # PmsError / ErrorCode 统一错误模型
        ├── transport.py         # urllib GET(query)/POST(body)/路径参数、超时、重试、归一
        ├── spec.py              # 加载 interfaces.json，生成 JSON Schema / 工具描述
        ├── client.py            # call_tool 统一入口 + 26 个同名显式方法
        └── mock.py              # 按 spec.mock 出数，支持分页与简单过滤
```

维护原则：

1. **单一事实源**：工具名、接口编码、path、method、参数、mock 全部来自 `spec/interfaces.json`；
   新增/修改接口只改 spec（必要时同步 `references/interfaces.md` 与本文件的工具清单）。
   `mock_gateway` 的路由也按 spec 动态生成，新增工具只需补 `mock_gateway/data.py` 的处理函数。
2. **签名可替换、不硬编码密钥**：appkey 签名是二期定义的「模拟规范」，唯一实现是
   `pms_client/signing.py`（客户端与模拟网关共用）；真实中台规范下发后只替换该实现，
   其余代码零改动。所有凭证只从环境变量读取，日志/自检只输出脱敏信息。
3. **不硬编码凭证**：凭证只从环境变量读取；日志与自检只输出脱敏信息。
4. **stdout 纯净**：任何新增诊断输出必须走 `log()`（stderr），否则会破坏 MCP 协议。
5. 改完跑回归：`python -m unittest discover -s tests -v`（26 个工具完整性、mock、分页过滤、错误归一、MCP 协议、CLI 参数全部覆盖；
   二期模拟网关的用例见 `tests/test_mock_gateway.py`）。

---

## 附录 A · 离线模拟数据（内网验证）

本目录是可独立安装/上传的拆分技能包。没有 PMS 中台时，`mock/samples.json` 提供本技能相关接口的
确定性模拟返回（字段与真实接口一致，数据虚构、仅用于演示），说明见 `mock/README.md`。

需要真实调用链时，配置 `pms-gateway-mcp`（本地模拟网关/stdio MCP 见
`standalone/mcp-servers/pms-gateway-mcp/README.md`）。模拟数据不得作为业务结论。
