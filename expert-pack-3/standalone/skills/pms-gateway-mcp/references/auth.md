# 鉴权接入说明

本技能默认 **mock 模式**（内置样例数据，不访问真实网关），拿到中台凭证后**只改环境变量**即可切换，
业务代码、MCP 工具、CLI 用法全部不变。二期（`expert-pack-2`）已按**模拟规范**实现 appkey 签名
（`scripts/pms_client/signing.py`，客户端与本地模拟网关共用）；真实中台规范下发后只需替换该实现。

更完整的申请流程、联调清单与 QPS/脱敏要求见专家包文档
[`docs/02-鉴权接入指南.md`](../../../docs/02-鉴权接入指南.md)（本文件只保留与代码强相关的部分，不重复细节）。

## 一、四种鉴权模式

| 模式 | 取值 | 请求头 | 何时使用 | 当前状态 |
|---|---|---|---|---|
| mock | `mock` | `X-PMS-Mock: 1` | 无凭证时的本地联调 / 演示 / 单测 | ✅ 默认、开箱可用 |
| none | `none` | 无鉴权头 | 内网直连、或网关代理已统一鉴权 | ✅ 代码就绪（需配置 `PMS_GATEWAY_BASE_URL`） |
| token | `token` | `Authorization: Bearer <PMS_TOKEN>` | 中台下发访问令牌（Token）后 | ✅ 代码就绪（需填 `PMS_TOKEN`） |
| appkey | `appkey` | `X-PMS-App-Key` / `X-PMS-Timestamp` / `X-PMS-Nonce` / `X-PMS-Signature` | 中台按 appKey/appSecret + HMAC 签名对接 | ✅ 已实现模拟规范（真实规范下发后替换 `signing.py`） |

对应的实现类（`scripts/pms_client/auth.py`）：

- `MockAuthProvider`、`NoneAuthProvider`、`TokenAuthProvider`、`AppKeyAuthProvider`
- 工厂函数 `create_auth_provider(config)`：未知模式抛 `AUTH_MODE_INVALID`

## 二、环境变量

| 变量 | 必填性 | 默认值 | 说明 |
|---|---|---|---|
| `PMS_AUTH_MODE` | 否 | `mock` | `mock` / `none` / `appkey` / `token` |
| `PMS_GATEWAY_BASE_URL` | 非 mock 模式必填 | 空 | 网关完整地址，如 `https://pms-gateway.example.com` |
| `PMS_APP_KEY` | appkey 模式必填 | 空 | 向中台申请的应用 key，**禁止写进代码/仓库** |
| `PMS_APP_SECRET` | appkey 模式必填 | 空 | 向中台申请的应用密钥，**禁止写进代码/仓库** |
| `PMS_TOKEN` | token 模式必填 | 空 | 中台下发的访问令牌 |
| `PMS_TIMEOUT` | 否 | `30` | 单次请求超时（秒） |
| `PMS_RETRY` | 否 | `1` | 失败重试次数（仅对网络/超时/429/5xx 生效） |
| `PMS_SPEC_PATH` | 否 | 自动定位 | 可选；发布 zip 已内置 spec 快照（`references/interfaces.json`），仅用于覆盖内置快照或本地调试 |
| `PMS_VERIFY_SSL` | 否 | `1` | `0` 表示跳过证书校验（仅限测试环境） |

> 缺凭证时的行为：`PmsConfig.validate()` / `check()` 抛出 `NOT_CONFIGURED`
> （如「token 模式缺少凭证：PMS_TOKEN 为空…」），CLI 退出码 1，MCP `tools/call` 返回 `isError:true`
> 并在 `content` 里带可操作提示；**不会静默失败，也不会用假数据冒充真实数据**。

## 三、从 mock 切到真实网关（三步）

```bash
# 1) 配置网关地址与鉴权模式（示例：token 模式）
export PMS_GATEWAY_BASE_URL="https://pms-gateway.example.com"   # PowerShell: $env:PMS_GATEWAY_BASE_URL="https://..."
export PMS_AUTH_MODE="token"
export PMS_TOKEN="<向中台申请的令牌>"

# 2) 自检：确认配置、spec、鉴权模式均无问题
python skills/pms-gateway-mcp/scripts/pms_cli.py doctor --no-probe

# 3) 灰度验证单个接口，确认返回结构与字段口径
python skills/pms-gateway-mcp/scripts/pms_cli.py call get_asset_by_id --params '{"assetId":"AST-102-0001"}'
```

切换完成后，MCP 宿主重新拉起 `mcp_server.py` 即可（MCP 与 CLI 共用同一套配置读取逻辑）。

## 四、appkey 签名规范（模拟实现）

- **实现文件**：`scripts/pms_client/signing.py`（**唯一实现**）；`AppKeyAuthProvider.build_headers(method, path, query, body)`
  负责生成 `timestamp`（毫秒）、`nonce`（uuid4 hex）并调用 `build_appkey_signature(...)`。
- **签名串（canonical，7 段，`\n` 连接）**：

  ```
  app_key
  METHOD             # 大写，如 GET / POST
  path               # 已替换路径参数的最终路径，不含 query
  canonical_query    # None 跳过；列表→逗号；布尔→true/false；排序后 urlencode
  body_sha256        # sha256(rawBody).hexdigest()，空 body 取 sha256(b"")
  timestamp          # 毫秒字符串，与 X-PMS-Timestamp 一致
  nonce              # 与 X-PMS-Nonce 一致
  ```

- **签名**：`HMAC-SHA256(appSecret, canonical)` → **小写 hex**，放入 `X-PMS-Signature`；同时携带
  `X-PMS-App-Key` / `X-PMS-Timestamp` / `X-PMS-Nonce`。本地网关校验 ±300 秒时间窗与 nonce 防重放。
- **固定样例（可直接复算）**：

  ```
  app_key=mock-app-key, secret=mock-app-secret, GET, /assetCenter/queryServices/getAstById,
  query={"assetId":"AST-102-0001"}, body=None, ts=1759000000000, nonce=n0nce
  canonical = mock-app-key\nGET\n/assetCenter/queryServices/getAstById\nassetId=AST-102-0001\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\n1759000000000\nn0nce
  signature = 24ebb6f933f0d6c52a018877389a97e39b1a327315e712269315ddcd5e2db906
  ```

- **接真实中台**：只替换 `signing.py` 的实现（必要时同步 `HEADER_*` 常量）；`transport` / `client` / CLI /
  MCP Server / 本地模拟网关自动跟随，无需改动。
- **安全红线**：`app_secret` 只能来自环境变量 `PMS_APP_SECRET`，函数内不得出现任何硬编码密钥；
  日志与 `describe()` 只输出脱敏后的 `appKeyMasked` / `hasAppSecret`。

## 五、联调检查清单

- [ ] `PMS_AUTH_MODE` 与持有的凭证类型一致（token ↔ `PMS_TOKEN`，appkey ↔ `PMS_APP_KEY`+`PMS_APP_SECRET`）
- [ ] `PMS_GATEWAY_BASE_URL` 可访问（内网需连通性/代理；必要时 `PMS_VERIFY_SSL=0` 仅限测试环境）
- [ ] `pms_cli.py doctor --no-probe` 的 `problems` 为空
- [ ] 单个只读接口（`get_asset_by_id`）先联调通过，再验证 POST 类业务接口
- [ ] 核对返回字段与 `spec/interfaces.json` 的 `responseHint`；字段不一致时**只改 spec**，不改客户端代码
- [ ] 记录频控/QPS 与数据脱敏要求，必要时增大 `PMS_TIMEOUT`、降低调用频率
- [ ] 生产切换前确认网关地址、鉴权环境（测试/生产）与日志脱敏配置

## 六、鉴权相关错误码

| 错误码 | 触发场景 | 处理建议 |
|---|---|---|
| `AUTH_MODE_INVALID` | `PMS_AUTH_MODE` 取到未知值 | 改为 `mock`/`none`/`appkey`/`token` |
| `AUTH_MISSING_CREDENTIALS` | 对应模式凭证为空 | 补环境变量；未申请到凭证先用 `mock` |
| `AUTH_SIGNATURE_TODO` | 历史错误码：appkey 签名未实现（二期已实现，不再抛出） | 保留用于兼容旧日志；升级 `expert-pack-2` 后无需处理 |
| `AUTH_FAILED` | 网关返回 401/403 | 凭证过期/无权限/签名不符，联系中台确认 |
| `NOT_CONFIGURED` | 非 mock 模式缺 `PMS_GATEWAY_BASE_URL` 等 | 补配置，或联调期用 `mock` |

完整错误码表见 `SKILL.md` 的「错误码」章节。

## 七、安全约束（硬性）

- 任何凭证都不得出现在代码、文档、测试、mock 数据、日志、提交记录中；本包已通过测试校验 `auth.py` 无私钥字面量。
- `PmsConfig.describe()` / `AuthProvider.describe()` 只输出 `hasAppKey`、`hasAppSecret`、`hasToken`、`appKeyMasked` 等脱敏信息。
- 对外回答中涉及手机号、身份证号、详细地址等敏感字段需脱敏（见专家包 `identify.md` 的约束）。
