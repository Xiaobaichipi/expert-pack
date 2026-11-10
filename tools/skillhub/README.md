# skillhub CLI（skillhub.cn，Windows 便携安装）

- 来源：skillhub.cn 官方安装包 `https://skillhub-1388575217.cos.ap-guangzhou.myqcloud.com/install/latest.tar.gz`（官方 `install.sh` 仅支持 Linux/macOS，Windows 下解包后直接用 Python 调用；本目录即 `cli/` 内容的副本）
- 版本：`2026.8.5`（见 `version.json`，`skillhub -v` 可查）
- 依赖：Python 3.8+（本机 3.9.24 已验证）
- 默认 API：`https://api.skillhub.cn`；企业源用 `--host` 或环境变量 `SKILLHUB_HOST`
- 入口：`skillhub.cmd`（PowerShell / cmd 均可）、`skillhub.ps1`

> 注意：同名的 npm 包 `@astron-team/skillhub` 是另一个项目（iflytek/skillhub，用 `suite` 模型，没有 `pack` 命令），不要混用。企业平台对应的是本目录这套（`login --key skh_...`、`pack install`、`publish`）。

## 常用命令

```powershell
# 版本
.\tools\skillhub\skillhub.cmd -v

# 登录企业源（token 形如 skh_... 或 sk-ent-...；会写 ~/.skillhub/credentials.json）
.\tools\skillhub\skillhub.cmd login --key skh_xxx --host https://<企业源>

# 安装专家包到 Agent「全局加载技能」目录（不是项目下 ./skills）
.\tools\skillhub\skillhub.cmd pack install <pack-slug> --dir "$env:USERPROFILE\.claude\skills" --json

# 发布单个技能（目录或 .zip；SKILL.md frontmatter 必须含 slug / version / displayName）
.\tools\skillhub\skillhub.cmd publish .\expert-pack\skills\pms-gateway-mcp --dry-run

# 自升级（会联网并写 ~/.skillhub）
.\tools\skillhub\skillhub.cmd self-upgrade
```

## 已核实的专家包机制（2026.8.5）

- `pack install <slug>` 先请求 `{host}/api/v1/skillsets/{slug}/download`，得到**清单包**：`manifest.json` + `identify.md`（实测公开专家包 `tech-test-automation` 仅这两个文件，约 6.8 KB，不含子技能 zip）。
- 再按 `manifest.skillSlugs` 逐个下载技能 zip（`{host}/api/v1/download?slug=<skill>`），装到 `<--dir>/<skill-slug>/`。
- 把 `identify.md` 写成 `<--dir>/<pack-slug>/SKILL.md`（专家包提示词本身也是一个技能目录），`soul.md` 写到 `--dir` 的父目录。
- 写入安装锁文件（记录 skills 与 packs）。
- 结论：专家包 = 平台侧「清单 + 编排提示词 + 技能 slug 引用」；子技能始终是独立 zip、独立安装目录。

## 加入 PATH（可选）

```powershell
# 当前会话
$env:Path += ";F:\work\2026年\10月\专家包\tools\skillhub"
# 永久（用户级环境变量，需重开终端）
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";F:\work\2026年\10月\专家包\tools\skillhub", "User")
```

## 更新

重新下载 `latest.tar.gz`，解包后用 `cli/` 下的 `skills_store_cli.py`、`skills_upgrade.py`、`version.json`、`metadata.json` 覆盖本目录（保留 `skillhub.cmd` / `skillhub.ps1`）。
