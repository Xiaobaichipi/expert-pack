#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""expert-pack-3 · 把每个技能与 MCP 拆成独立可交付包，并生成离线模拟数据。

产物（全部确定性，可重复构建）：
    standalone/
      README.md                     # 内网使用总说明
      index.json                    # 拆分包索引
      verify_offline.py             # 复制自 tools/verify_standalone.py
      skills/<slug>/                # 12 个独立技能目录（SKILL.md + 资源 + mock/）
      mcp-servers/<slug>/           # 2 个独立 MCP 目录（+ README/启动脚本）
      mcp-config/                   # 宿主 MCP 配置模板 + 生成脚本
    dist-standalone/
      skills/<slug>.zip             # 12 个技能上传包
      mcp/<slug>.zip                # 2 个 MCP 分发包
      checksums.txt                 # SHA256

模拟数据来源：skills/pms-gateway-mcp/scripts/mock_gateway/data.py（虚构）；
分析侧来自 substation-analysis-mcp/assets/demo_bundle.json + 分析引擎实算结果。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
SPEC = ROOT / "spec" / "interfaces.json"
STANDALONE = ROOT / "standalone"
DIST = ROOT / "dist-standalone"

sys.path.insert(0, str(SKILLS / "pms-gateway-mcp" / "scripts"))
sys.path.insert(0, str(SKILLS / "substation-analysis-mcp" / "scripts"))

from mock_gateway import data as mock_data  # noqa: E402
import analysis  # noqa: E402

FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
MCP_SLUGS = ("pms-gateway-mcp", "substation-analysis-mcp")
EXCLUDE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".git"})
EXCLUDE_SUFFIXES = (".pyc", ".pyo")

# ---------------------------------------------------------------------------
# 模拟样例：每个技能用它最常用的接口，参数取真实模拟主键
# ---------------------------------------------------------------------------
PMS_SAMPLE_ARGS: dict[str, dict[str, Any]] = {
    "list_asset_params": {"assetType": "transformer", "stationId": "STA-220-01"},
    "get_asset_by_id": {"assetId": "AST-102-0001"},
    "get_psr_by_id": {"psrId": "PSR-220-0001"},
    "get_device_by_utc_num": {"utcNum": "UTC-2020-000123"},
    "get_device_tree_root": {},
    "get_device_tree_nodes": {"parentId": "ROOT"},
    "list_psr_by_filters": {"stationId": "STA-220-01"},
    "query_svg_map_by_psr_id": {"psrId": "PSR-220-0001"},
    "search_power_path": {"psrId": "PSR-220-0001"},
    "analyze_supply_area": {"psrId": "PSR-220-0001", "direction": "outage"},
    "inquire_defect": {"defectLevel": "严重"},
    "view_defect": {"defectId": "DF-2026-0001"},
    "list_hazard": {"stationId": "STA-220-01"},
    "list_fault_trip_records": {"deviceId": "AST-102-0001"},
    "get_repair_plan": {"stationId": "STA-220-01"},
    "find_repair_test": {"pageSize": 50},
    "find_repair_program": {"deviceId": "AST-102-0001"},
    "list_test_item": {},
    "list_patrol_plan": {"stationId": "STA-220-01"},
    "list_patrol_record": {"stationId": "STA-220-01"},
    "query_open_capacity": {"stationId": "STA-220-01"},
    "query_station_scale_analysis": {"stationId": "STA-220-01"},
    "query_outage_incident": {"stationId": "STA-220-01"},
    "find_smart_device": {"stationId": "STA-220-01"},
    "get_instrument_list": {"stationId": "STA-220-01"},
    "get_manufacturer_infos": {},
}

#: 每个“提示词型”技能单独拆包时附带的模拟调用（tool, 参数, 说明）
SKILL_CALLS: dict[str, list[tuple[str, dict[str, Any], str]]] = {
    "substation-asset-ledger": [
        ("get_asset_by_id", {"assetId": "AST-102-0001"}, "按资产ID查台账"),
        ("list_asset_params", {"assetType": "transformer", "stationId": "STA-220-01"}, "全站主变容量参数"),
        ("get_device_by_utc_num", {"utcNum": "UTC-2020-000123"}, "实物ID扫码定位"),
        ("list_psr_by_filters", {"stationId": "STA-220-01"}, "按站查资源清单"),
    ],
    "substation-device-tree": [
        ("get_device_tree_root", {}, "设备树根节点"),
        ("get_device_tree_nodes", {"parentId": "ROOT"}, "根下变电站节点"),
        ("list_psr_by_filters", {"stationId": "STA-220-01"}, "站点下 PSR 资源"),
    ],
    "substation-diagnosis": [
        ("get_asset_by_id", {"assetId": "AST-102-0001"}, "设备身份"),
        ("inquire_defect", {"deviceId": "AST-102-0001"}, "设备缺陷"),
        ("view_defect", {"defectId": "DF-2026-0001"}, "缺陷详情"),
        ("list_fault_trip_records", {"deviceId": "AST-102-0001"}, "故障跳闸记录"),
        ("find_repair_test", {"deviceId": "AST-102-0001"}, "修试记录"),
        ("list_hazard", {"stationId": "STA-220-01"}, "站内隐患"),
    ],
    "substation-health-assessment": [
        ("get_asset_by_id", {"assetId": "AST-102-0001"}, "设备身份"),
        ("query_open_capacity", {"deviceId": "AST-102-0001"}, "负载/容量"),
        ("query_station_scale_analysis", {"stationId": "STA-220-01"}, "站可靠性"),
        ("inquire_defect", {"deviceId": "AST-102-0001"}, "缺陷"),
        ("find_repair_test", {"deviceId": "AST-102-0001"}, "修试"),
    ],
    "substation-maintenance-test": [
        ("get_repair_plan", {"stationId": "STA-220-01"}, "检修计划"),
        ("find_repair_test", {"pageSize": 50}, "修试记录"),
        ("find_repair_program", {"deviceId": "AST-102-0001"}, "检修方案"),
        ("list_patrol_plan", {"stationId": "STA-220-01"}, "巡视计划"),
        ("list_patrol_record", {"stationId": "STA-220-01"}, "巡视记录"),
        ("list_test_item", {}, "试验项目标准"),
    ],
    "substation-om-health": [
        ("inquire_defect", {"pageSize": 20}, "全部缺陷"),
        ("view_defect", {"defectId": "DF-2026-0001"}, "缺陷详情"),
        ("list_fault_trip_records", {"pageSize": 20}, "故障跳闸"),
        ("list_hazard", {"stationId": "STA-220-01"}, "隐患"),
    ],
    "substation-qa-orchestrator": [
        ("get_asset_by_id", {"assetId": "AST-102-0001"}, "设备身份"),
        ("list_psr_by_filters", {"stationId": "STA-220-01"}, "站内资源"),
        ("get_device_tree_nodes", {"parentId": "ROOT"}, "设备树"),
        ("query_open_capacity", {"stationId": "STA-220-01"}, "容量"),
        ("query_station_scale_analysis", {"stationId": "STA-220-01"}, "可靠性"),
        ("search_power_path", {"psrId": "PSR-220-0001"}, "供电路径"),
        ("analyze_supply_area", {"psrId": "PSR-220-0001", "direction": "outage"}, "停电影响"),
    ],
    "substation-reliability": [
        ("query_station_scale_analysis", {"stationId": "STA-220-01"}, "站可靠性指标"),
        ("query_outage_incident", {"stationId": "STA-220-01"}, "停电事件"),
        ("query_open_capacity", {"stationId": "STA-220-01"}, "容量"),
        ("analyze_supply_area", {"psrId": "PSR-220-0001", "direction": "outage"}, "停电影响范围"),
    ],
    "substation-report": [
        ("get_asset_by_id", {"assetId": "AST-102-0001"}, "设备身份"),
        ("inquire_defect", {"deviceId": "AST-102-0001"}, "缺陷"),
        ("find_repair_test", {"pageSize": 50}, "修试"),
        ("get_repair_plan", {"stationId": "STA-220-01"}, "检修计划"),
        ("list_patrol_record", {"stationId": "STA-220-01"}, "巡视记录"),
        ("query_open_capacity", {"deviceId": "AST-102-0001"}, "负载"),
        ("query_station_scale_analysis", {"stationId": "STA-220-01"}, "可靠性"),
    ],
    "substation-resource-topology": [
        ("get_psr_by_id", {"psrId": "PSR-220-0001"}, "PSR 详情"),
        ("query_svg_map_by_psr_id", {"psrId": "PSR-220-0001"}, "接线图"),
        ("search_power_path", {"psrId": "PSR-220-0001"}, "供电路径"),
        ("analyze_supply_area", {"psrId": "PSR-220-0001", "direction": "outage"}, "停电影响"),
        ("find_smart_device", {"stationId": "STA-220-01"}, "站内智能装置"),
        ("get_instrument_list", {"stationId": "STA-220-01"}, "仪器仪表"),
        ("get_manufacturer_infos", {}, "厂家信息"),
    ],
}

MOCK_NOTE = "模拟数据，仅用于内网联调/演示；不得作为业务结论或真实数据使用。"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        item = re.match(r"^[A-Za-z_][A-Za-z0-9_-]*:\s*(.+)$", line)
        if item:
            result[line.split(":", 1)[0].strip()] = item.group(1).strip().strip("\"'")
    return result


def trim_payload(payload: Any) -> Any:
    """分页响应只保留前 2 条，total 保留，避免样例文件过大。"""
    if isinstance(payload, dict) and isinstance(payload.get("list"), list):
        full = payload["list"]
        out = dict(payload)
        out["list"] = full[:2]
        out["listTruncated"] = len(full) > 2
        return out
    return payload


def copy_tree_clean(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        str(src),
        str(dst),
        ignore=shutil.ignore_patterns(*EXCLUDE_DIRS, "*.pyc", "*.pyo"),
    )


def write_zip(dest: Path, base: Path) -> None:
    entries: list[tuple[str, bytes]] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(base).parts
        if any(part in EXCLUDE_DIRS for part in rel_parts):
            continue
        if path.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        entries.append((path.relative_to(base).as_posix(), path.read_bytes()))
    entries.sort(key=lambda item: item[0])
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with zipfile.ZipFile(str(tmp), "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, content in entries:
            info = zipfile.ZipInfo(filename=arcname, date_time=FIXED_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, content)
    tmp.replace(dest)


def build_mock_samples(slug: str, frontmatter: dict[str, str]) -> dict[str, Any]:
    meta = {
        "skill": slug,
        "displayName": frontmatter.get("displayName", slug),
        "version": frontmatter.get("version", ""),
        "note": MOCK_NOTE,
        "dataSource": "skills/pms-gateway-mcp/scripts/mock_gateway/data.py",
        "deterministic": True,
    }
    if slug == "substation-analysis-mcp":
        bundle = read_json(SKILLS / slug / "assets" / "demo_bundle.json")
        health = analysis.assess_device_health(bundle)
        diagnosis = analysis.diagnose_equipment(bundle)
        metrics = analysis.compute_device_metrics(bundle)
        patterns = analysis.detect_defect_patterns(
            bundle.get("defects", []),
            device_meta=bundle.get("device"),
            window_days=365,
            family_min_count=2,
        )
        station = analysis.assess_station_health([bundle], station_meta=bundle.get("device"), top_n=3)
        meta.update(
            {
                "kind": "mcp",
                "demoBundle": "assets/demo_bundle.json",
                "cliExamples": [
                    "python scripts/analysis_cli.py demo",
                    "python scripts/analysis_cli.py health --bundle assets/demo_bundle.json",
                    "python scripts/analysis_cli.py report --type device_profile --bundle assets/demo_bundle.json",
                ],
                "results": {
                    "health": health,
                    "diagnosis": diagnosis,
                    "metrics": metrics,
                    "patterns": patterns,
                    "stationHealth": station,
                },
            }
        )
        return meta

    if slug == "pms-gateway-mcp":
        meta.update(
            {
                "kind": "mcp",
                "cliExamples": [
                    "python scripts/pms_cli.py doctor",
                    "python scripts/pms_cli.py mock-server --auth-mode token --port 18080",
                    'python scripts/pms_cli.py call get_asset_by_id --params "{\\"assetId\\":\\"AST-102-0001\\"}"',
                    "python scripts/mcp_server.py  # stdio MCP（配 PMS_AUTH_MODE=mock）",
                ],
            }
        )
        calls = []
        for tool in mock_data.HANDLERS:
            args = dict(PMS_SAMPLE_ARGS.get(tool, {}))
            calls.append(
                {
                    "tool": tool,
                    "params": args,
                    "response": trim_payload(mock_data.handle(tool, args)),
                }
            )
        meta["calls"] = calls
        return meta

    calls = []
    for tool, args, note in SKILL_CALLS.get(slug, []):
        calls.append(
            {
                "tool": tool,
                "params": args,
                "note": note,
                "response": trim_payload(mock_data.handle(tool, args)),
            }
        )
    meta["kind"] = "skill"
    meta["calls"] = calls
    return meta


def mock_readme(slug: str, sample: dict[str, Any]) -> str:
    kind = sample.get("kind")
    if slug == "substation-analysis-mcp":
        detail = (
            "- `results`：用 `assets/demo_bundle.json` 实算的健康度/诊断/指标/模式/站级画像；\n"
            "- `cliExamples`：离线可运行的 CLI 命令；\n"
            "- `demoBundle`：演示数据包（1号主变，含严重缺陷/跳闸/不合格试验）。\n"
        )
    elif slug == "pms-gateway-mcp":
        detail = (
            "- `calls`：26 个 PMS 接口各 1 条模拟返回（分页列表截断为前 2 条，total 保留）；\n"
            "- 本地模拟网关：`python scripts/pms_cli.py mock-server --auth-mode token --port 18080`；\n"
            "- 默认 mock 模式无需网关：`python scripts/pms_cli.py doctor` / `call`。\n"
        )
    else:
        detail = (
            "- `calls`：本技能最常用的 PMS 接口模拟返回（分页列表截断为前 2 条，total 保留）；\n"
            "- 每个调用含 `tool`、`params`、`response`，可直接作为 Agent/脚本的模拟输入。\n"
        )
    return (
        "# 离线模拟数据 · {slug}\n\n"
        "{note}\n\n"
        "## 文件说明\n\n"
        "{detail}"
        "\n## 使用方式（内网无 PMS 中台时）\n\n"
        "1. 按 `samples.json` 中 `tool`/`params` 理解该技能的入参；\n"
        "2. 用 `response` 作为模拟返回走通技能流程（字段与真实接口一致）；\n"
        "3. 需要真实调用链时，配置同级的 `pms-gateway-mcp` MCP 或本地模拟网关。\n"
        "\n> 数据来源 `mock_gateway/data.py`（虚构，确定性）；完整数据/全部接口请运行模拟网关。\n"
    ).format(slug=slug, note=MOCK_NOTE, detail=detail)


SKILL_APPENDIX = """
---

## 附录 A · 离线模拟数据（内网验证）

本目录是可独立安装/上传的拆分技能包。没有 PMS 中台时，`mock/samples.json` 提供本技能相关接口的
确定性模拟返回（字段与真实接口一致，数据虚构、仅用于演示），说明见 `mock/README.md`。

需要真实调用链时，配置 `pms-gateway-mcp`（本地模拟网关/stdio MCP 见
`standalone/mcp-servers/pms-gateway-mcp/README.md`）。模拟数据不得作为业务结论。
"""


# ---------------------------------------------------------------------------
# 构建
# ---------------------------------------------------------------------------
def build() -> int:
    manifest = read_json(ROOT / "manifest.json")
    slugs: list[str] = list(manifest["skillSlugs"])
    spec = read_json(SPEC)
    spec_tools = {item["name"] for item in spec["tools"]}

    for target in (STANDALONE / "skills", STANDALONE / "mcp-servers", DIST):
        if target.exists():
            shutil.rmtree(target)
    (STANDALONE / "skills").mkdir(parents=True, exist_ok=True)
    (STANDALONE / "mcp-servers").mkdir(parents=True, exist_ok=True)
    (DIST / "skills").mkdir(parents=True, exist_ok=True)
    (DIST / "mcp").mkdir(parents=True, exist_ok=True)

    index_skills: list[dict[str, Any]] = []
    index_mcp: list[dict[str, Any]] = []

    for slug in slugs:
        src = SKILLS / slug
        dst = STANDALONE / "skills" / slug
        copy_tree_clean(src, dst)

        skill_md = (dst / "SKILL.md").read_text(encoding="utf-8")
        fm = parse_frontmatter(skill_md)
        if slug == "pms-gateway-mcp":
            # 独立包必须自带 spec 快照，否则脱离专家包根目录后找不到 interfaces.json
            (dst / "references").mkdir(exist_ok=True)
            (dst / "references" / "interfaces.json").write_bytes(SPEC.read_bytes())

        sample = build_mock_samples(slug, fm)
        mock_dir = dst / "mock"
        mock_dir.mkdir(exist_ok=True)
        (mock_dir / "samples.json").write_text(
            json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (mock_dir / "README.md").write_text(mock_readme(slug, sample), encoding="utf-8")

        if "附录 A · 离线模拟数据" not in skill_md:
            (dst / "SKILL.md").write_text(skill_md.rstrip() + "\n" + SKILL_APPENDIX, encoding="utf-8")

        call_count = len(sample.get("calls") or [])
        if not call_count and isinstance(sample.get("results"), dict):
            call_count = len(sample["results"])
        zip_path = DIST / "skills" / (slug + ".zip")
        write_zip(zip_path, dst)
        index_skills.append(
            {
                "slug": slug,
                "displayName": fm.get("displayName", slug),
                "version": fm.get("version", ""),
                "kind": sample.get("kind"),
                "directory": "standalone/skills/" + slug,
                "zip": "dist-standalone/skills/" + slug + ".zip",
                "mockSamples": "standalone/skills/{}/mock/samples.json".format(slug),
                "mockCallCount": call_count,
            }
        )

        if slug in MCP_SLUGS:
            mcp_dst = STANDALONE / "mcp-servers" / slug
            copy_tree_clean(dst, mcp_dst)
            (mcp_dst / "README.md").write_text(mcp_readme(slug, sample), encoding="utf-8")
            write_mcp_scripts(slug, mcp_dst)
            write_zip(DIST / "mcp" / (slug + ".zip"), mcp_dst)
            index_mcp.append(
                {
                    "slug": slug,
                    "displayName": fm.get("displayName", slug),
                    "version": fm.get("version", ""),
                    "directory": "standalone/mcp-servers/" + slug,
                    "zip": "dist-standalone/mcp/" + slug + ".zip",
                    "transport": "stdio",
                }
            )

    # MCP 配置模板与生成脚本
    write_mcp_config_files()

    # standalone/verify_offline.py（从 tools/verify_standalone.py 复制）
    verifier_src = Path(__file__).resolve().parent / "verify_standalone.py"
    if not verifier_src.is_file():
        raise SystemExit("缺少 tools/verify_standalone.py，请先创建校验脚本")
    shutil.copyfile(verifier_src, STANDALONE / "verify_offline.py")

    # index.json
    index = {
        "packSlug": manifest["slug"],
        "packDisplayName": manifest.get("displayName", ""),
        "packVersion": manifest.get("version", ""),
        "skillCount": len(index_skills),
        "mcpCount": len(index_mcp),
        "specToolCount": len(spec_tools),
        "skills": index_skills,
        "mcpServers": index_mcp,
        "note": MOCK_NOTE,
    }
    (STANDALONE / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (STANDALONE / "README.md").write_text(standalone_readme(index), encoding="utf-8")

    # checksums.txt
    checks: list[tuple[str, str]] = []
    for path in sorted(DIST.rglob("*.zip")):
        checks.append((path.relative_to(DIST).as_posix(), sha256(path.read_bytes())))
    checks.sort()
    lines = ["%s  %s" % (digest, name) for name, digest in checks]
    (DIST / "checksums.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("== expert-pack-3 独立拆分包构建完成 ==")
    print("技能目录：standalone/skills/（%d 个）" % len(index_skills))
    print("MCP 目录：standalone/mcp-servers/（%d 个）" % len(index_mcp))
    print("上传包：dist-standalone/skills/*.zip（%d）、dist-standalone/mcp/*.zip（%d）" % (len(index_skills), len(index_mcp)))
    print("校验清单：dist-standalone/checksums.txt（%d 项）" % len(checks))
    print("模拟样例：每包 mock/samples.json（PMS 26 接口 + 分析引擎实算结果）")
    return 0


# ---------------------------------------------------------------------------
# MCP 说明 / 启动脚本 / 配置
# ---------------------------------------------------------------------------
def mcp_readme(slug: str, sample: dict[str, Any]) -> str:
    if slug == "pms-gateway-mcp":
        body = """# pms-gateway-mcp（独立 MCP 包）

PMS 接口网关 MCP：26 个工具，默认 mock 模式（无需真实中台/凭证）；也可启动本地可鉴权模拟网关（token/appkey）。

## 运行方式

```powershell
$here = (Resolve-Path .).Path

# 1) 自检（无需网络）
python "$here\\scripts\\pms_cli.py" doctor

# 2) 单次 mock 调用
python "$here\\scripts\\pms_cli.py" call get_asset_by_id --params '{{"assetId":"AST-102-0001"}}'

# 3) 本地可鉴权网关（HTTP，token；Ctrl+C 退出）
python "$here\\scripts\\pms_cli.py" mock-server --auth-mode token --host 127.0.0.1 --port 18080

# 4) stdio MCP（宿主挂载）
python "$here\\scripts\\mcp_server.py"
```

## 宿主 MCP 配置（stdio）

```json
{{
  "mcpServers": {{
    "pms-gateway": {{
      "command": "python",
      "args": ["<本目录绝对路径>/scripts/mcp_server.py"],
      "env": {{"PMS_AUTH_MODE": "mock"}}
    }}
  }}
}}
```

也可直接运行 `mcp-config/make_mcp_config.py` 生成绝对路径配置。

## 离线数据

- 自带 `references/interfaces.json`（spec 快照，脱离专家包根目录也能解析）；
- `mock/samples.json`：26 个接口的模拟返回（数据虚构）；
- 默认常量：token=`mock-token-001`、app_key=`mock-app-key`、secret=`mock-app-secret`；
- 仅标准库（Python 3.9+），不依赖外网。
"""
    else:
        body = """# substation-analysis-mcp（独立 MCP 包）

变电分析引擎 MCP：7 个工具（健康度/站级画像/诊断/缺陷模式/派生指标/报告模板/报告渲染），纯 Python、无网络依赖。

## 运行方式

```powershell
$here = (Resolve-Path .).Path

# 1) 一条命令跑通全部分析（自带演示数据包）
python "$here\\scripts\\analysis_cli.py" demo

# 2) 单设备健康分 / 诊断 / 报告
python "$here\\scripts\\analysis_cli.py" health   --bundle "$here\\assets\\demo_bundle.json"
python "$here\\scripts\\analysis_cli.py" diagnose --bundle "$here\\assets\\demo_bundle.json"
python "$here\\scripts\\analysis_cli.py" report   --type device_profile --bundle "$here\\assets\\demo_bundle.json"

# 3) stdio MCP（宿主挂载）
python "$here\\scripts\\analysis_mcp.py"
```

## 宿主 MCP 配置（stdio）

```json
{{
  "mcpServers": {{
    "substation-analysis": {{
      "command": "python",
      "args": ["<本目录绝对路径>/scripts/analysis_mcp.py"]
    }}
  }}
}}
```

## 离线数据

- `assets/demo_bundle.json`：演示数据包（1号主变，含严重缺陷/跳闸/不合格试验，预期健康分 75.8 / C）；
- `mock/samples.json`：引擎实算的健康分、诊断、指标、模式、站级画像结果；
- `config/` + `templates/`：评分卡、诊断规则库、报告模板，随包自带。
"""
    return body


def write_mcp_scripts(slug: str, mcp_dst: Path) -> None:
    if slug == "pms-gateway-mcp":
        (mcp_dst / "run-mock-gateway.ps1").write_text(
            "$here = Split-Path -Parent $MyInvocation.MyCommand.Path\n"
            "python \"$here\\scripts\\pms_cli.py\" mock-server --auth-mode token --host 127.0.0.1 --port 18080\n",
            encoding="utf-8",
        )
        (mcp_dst / "run-stdio.ps1").write_text(
            "$here = Split-Path -Parent $MyInvocation.MyCommand.Path\n"
            "$env:PMS_AUTH_MODE = \"mock\"\n"
            "python \"$here\\scripts\\mcp_server.py\"\n",
            encoding="utf-8",
        )
    else:
        (mcp_dst / "run-stdio.ps1").write_text(
            "$here = Split-Path -Parent $MyInvocation.MyCommand.Path\n"
            "python \"$here\\scripts\\analysis_mcp.py\"\n",
            encoding="utf-8",
        )
    (mcp_dst / "requirements.txt").write_text(
        "# 仅使用 Python 3.9+ 标准库，无第三方依赖\n", encoding="utf-8"
    )


def write_mcp_config_files() -> None:
    config_dir = STANDALONE / "mcp-config"
    config_dir.mkdir(parents=True, exist_ok=True)
    template = {
        "mcpServers": {
            "pms-gateway": {
                "command": "python",
                "args": ["REPLACE_ME/standalone/mcp-servers/pms-gateway-mcp/scripts/mcp_server.py"],
                "env": {"PMS_AUTH_MODE": "mock"},
            },
            "substation-analysis": {
                "command": "python",
                "args": ["REPLACE_ME/standalone/mcp-servers/substation-analysis-mcp/scripts/analysis_mcp.py"],
            },
        }
    }
    (config_dir / "mcp-config.example.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (config_dir / "make_mcp_config.py").write_text(
        '''#!/usr/bin/env python3
"""生成带绝对路径的 MCP 配置（内网 Windows/Linux 通用）。

用法：python standalone/mcp-config/make_mcp_config.py
输出：同目录 mcp-config.generated.json
"""
from __future__ import annotations

import json
from pathlib import Path

STANDALONE = Path(__file__).resolve().parents[1]
MCP = STANDALONE / "mcp-servers"


def main() -> int:
    config = {
        "mcpServers": {
            "pms-gateway": {
                "command": "python",
                "args": [(MCP / "pms-gateway-mcp" / "scripts" / "mcp_server.py").as_posix()],
                "env": {"PMS_AUTH_MODE": "mock"},
            },
            "substation-analysis": {
                "command": "python",
                "args": [(MCP / "substation-analysis-mcp" / "scripts" / "analysis_mcp.py").as_posix()],
            },
        }
    }
    out = Path(__file__).resolve().parent / "mcp-config.generated.json"
    out.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    print("已生成：" + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
        encoding="utf-8",
    )


def standalone_readme(index: dict[str, Any]) -> str:
    skill_rows = "\n".join(
        "| {} | {} | {} | `mock/samples.json`（{} 条） |".format(
            item["slug"], item["displayName"], item["kind"], item["mockCallCount"]
        )
        for item in index["skills"]
    )
    mcp_rows = "\n".join(
        "| {} | {} | stdio |".format(item["slug"], item["displayName"])
        for item in index["mcpServers"]
    )
    return """# standalone · 内网验证包（{pack_name}）

本目录把专家包 **拆成 12 个独立技能 + 2 个独立 MCP**，每个包都自带离线模拟数据，
可整目录拷贝到内网电脑（无需外网、无需真实 PMS 中台/凭证）验证效果。

> 所有模拟数据均为虚构，仅用于联调/演示，不得作为业务结论。

## 一、一分钟自检

```powershell
cd expert-pack-3
python standalone/verify_offline.py
```

期望：逐项 PASS（12 技能包 / 2 MCP / 26 接口样例 / 分析引擎 75.8 / MCP stdio 协议）。

## 二、12 个独立技能包

技能目录可直接复制到宿主技能目录，或上传 `dist-standalone/skills/<slug>.zip`。

| slug | 名称 | 类型 | 模拟样例 |
|---|---|---|---|
{skill_rows}

每个技能目录结构：`SKILL.md`（含附录 A 离线数据说明）+ `references/` 等原始资源 + `mock/samples.json`。

## 三、2 个独立 MCP

| slug | 名称 | 传输 |
|---|---|---|
{mcp_rows}

- 目录：`standalone/mcp-servers/<slug>/`（含 `README.md`、`run-stdio.ps1`、`requirements.txt`）
- 上传包：`dist-standalone/mcp/<slug>.zip`
- **pms-gateway-mcp**：默认 mock 模式；自带 `references/interfaces.json`，可脱离专家包运行；
  `scripts/pms_cli.py doctor` 应返回 26 个工具；`mock-server` 可本地起 token/appkey 鉴权网关。
- **substation-analysis-mcp**：自带评分卡/规则库/报告模板/演示数据包；
  `scripts/analysis_cli.py demo` 应输出健康分 75.8。
- 仅依赖 Python 3.9+ 标准库，无第三方包、无网络访问。

## 四、宿主 MCP 配置

```powershell
python standalone/mcp-config/make_mcp_config.py
```

生成 `standalone/mcp-config/mcp-config.generated.json`（绝对路径），合并到宿主的 MCP 配置文件即可；
模板见 `mcp-config.example.json`。

## 五、模拟数据说明

- 数据规模：4 站 / 9 设备 / 13 PSR / 47 树节点 / 6 缺陷 / 4 隐患 / 3 故障 / 3 检修计划 / 3 试验 /
  3 巡视 / 4 容量 / 3 可靠性 / 3 停电 / 3 智能装置 / 3 仪表 / 3 厂家；
- 主键一致：`AST-102-0001 ↔ PSR-220-0001 ↔ UTC-2020-000123 ↔ TOPO-220-0001`；
- PMS 侧：`skills/pms-gateway-mcp` 自带 `mock/samples.json`（26 接口）；
- 分析侧：`substation-analysis-mcp` 自带 `assets/demo_bundle.json` + `mock/samples.json`（实算结果）。

## 六、限制

1. 模拟数据不代表真实设备/业务；
2. 技能包上传到平台需平台支持（本目录只提供 zip 与目录）；
3. MCP 宿主需自行配置 stdio（见第四节）；
4. 真实 PMS 接入、真实签名规范仍需企业环境联调。
""".format(
        pack_name=index.get("packDisplayName") or index.get("packSlug"),
        skill_rows=skill_rows,
        mcp_rows=mcp_rows,
    )


if __name__ == "__main__":
    raise SystemExit(build())
