#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""变电智能问数专家包 —— 构建、校验与打包脚本（Python 3.9+，仅标准库）。

功能
----
1. 契约校验：
   - spec/interfaces.json：tools 数量 = 26、工具 name/code 唯一、group 合法且 toolCount 一致；
   - spec/analysis-tools.json：存在、tools 数量 = 7、name 全局唯一且合法、参数 required 合法
     （布尔值、required 参数排在可选参数之前、required 参数不得带 default）、enum 合法；
   - spec/analysis-bundle.schema.json：合法 JSON，且具备 object 根、required 含 device、
     device.required 含 name 等最小契约结构；
   - manifest.json：平台 SkillSet 清单形态（manifestVersion="1"、type="skillset"、
     slug、displayName、summary、skillSlugs；scene/subScene 选填），前两项为底座技能、
     末尾为问数总控（技能数量从 manifest 动态读取，不硬编码）；
   - skills/<slug>/SKILL.md：存在且 frontmatter 含 name（=目录名）、slug（=目录名，
     平台 publish 必填）、displayName（平台 publish 必填）、version（SemVer）、description；
   - identify.md 存在且 frontmatter name 与专家包 slug 一致、version 为 SemVer。
2. 打包（幂等，可重复执行，产物字节稳定）：
   - dist/skills/<slug>.zip：zip 根即技能根（SKILL.md 在根）；
   - 底座技能 pms-gateway-mcp 的 zip 内置 spec 快照 references/interfaces.json
     （内容 = spec/interfaces.json 原始字节；构建生成件，唯一事实源仍是 spec/）；
   - 底座技能 substation-analysis-mcp 的 zip 必须内置分析引擎资产：
     config/scorecard.json、config/diagnosis_rules.json、templates/ 下 3 个报告模板、
     assets/demo_bundle.json（缺一即失败；其余技能不得包含这些文件）；
   - dist/<pack-slug>-bundle.zip：平台专家包清单包 = 构建生成的 manifest.json + identify.md
     （manifest 的 skills[]/files[] 由 SKILL.md frontmatter 与 identify.md 字节生成，
     与 skillhub.cn 实际下载的清单结构一致；不含子技能 zip）；
   - dist/checksums.txt：sha256 + 文件相对路径。
3. 每个 zip 均校验 < 10MB（平台限制）。

用法
----
    python expert-pack/tools/build_pack.py
    python expert-pack/tools/build_pack.py --src expert-pack --out expert-pack/dist
    python expert-pack/tools/build_pack.py --validate-only
    python expert-pack/tools/build_pack.py --allow-missing   # 技能未齐全时临时验证流程，禁止用于正式发布

退出码：0 = 成功；1 = 校验/打包失败（原因以中文打印）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import traceback
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── 常量 ────────────────────────────────────────────────────────────────────────
EXPECTED_PMS_TOOL_COUNT = 26       # spec/interfaces.json 中 PMS 工具数量（新增接口时同步修改，见 docs/04）
EXPECTED_ANALYSIS_TOOL_COUNT = 7   # spec/analysis-tools.json 中分析工具数量（v1.1 契约，见 docs/04）
MAX_ZIP_BYTES = 10 * 1024 * 1024   # 平台单包上限 10MB
PACK_ZIP_LIMIT_MB = 10

EXCLUDE_DIR_NAMES = frozenset({
    "__pycache__", ".git", ".idea", ".vscode", "node_modules", "dist",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hg", ".svn",
})
EXCLUDE_FILE_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
EXCLUDE_FILE_SUFFIXES = (".pyc", ".pyo")

# 底座技能：发布 zip 内置 spec 快照，保证 skillhub 单独安装后「装完即用」。
# pms_client/config.py 的 find_spec_path 会查找 <技能根>/references/interfaces.json；
# 快照是构建生成件，唯一事实源仍是 expert-pack/spec/interfaces.json。
SPEC_SNAPSHOT_SKILL = "pms-gateway-mcp"
SPEC_SNAPSHOT_ARCNAME = "references/interfaces.json"

# 分析底座技能：发布 zip 必须内置确定性计算所需的资产（评分卡 / 规则库 / 模板 / 演示数据包）。
ANALYSIS_SKILL = "substation-analysis-mcp"
ANALYSIS_SPEC_REL = "spec/analysis-tools.json"
ANALYSIS_BUNDLE_SCHEMA_REL = "spec/analysis-bundle.schema.json"
ANALYSIS_INPUT_CONTRACT = "spec/analysis-bundle.schema.json"
ANALYSIS_REQUIRED_ARCNAMES = (
    "config/scorecard.json",
    "config/diagnosis_rules.json",
    "templates/device_profile.md",
    "templates/station_monthly.md",
    "templates/fault_review.md",
    "assets/demo_bundle.json",
)
ANALYSIS_JSON_ARCNAMES = (
    "config/scorecard.json",
    "config/diagnosis_rules.json",
    "assets/demo_bundle.json",
)

# 技能顺序契约：两个底座在最前，问数总控在最后（发布顺序与路由依赖都依赖它）。
BASE_SKILL_SLUGS = ("pms-gateway-mcp", "substation-analysis-mcp")
ORCHESTRATOR_SKILL = "substation-qa-orchestrator"

VALID_PARAM_TYPES = frozenset({"string", "integer", "number", "boolean", "object", "array"})

# 固定 zip 内时间戳，保证同样输入产生同样字节（校验和稳定，便于比对）
FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")

# 平台专家包（SkillSet）清单契约：以下字段与 skillhub.cn 实际下载的清单一致。
MANIFEST_VERSION = "1"
MANIFEST_TYPE = "skillset"
BUNDLE_MANIFEST_NAME = "manifest.json"
BUNDLE_IDENTIFY_NAME = "identify.md"


class BuildError(Exception):
    """可预期的校验/打包失败，消息为中文，直接打印给使用者。"""


# ── 基础工具 ────────────────────────────────────────────────────────────────────
def _setup_console() -> None:
    """尽量把标准输出/错误切到 UTF-8，避免 Windows 控制台中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _fmt_size(size: int) -> str:
    if size >= 1024 * 1024:
        return "%.2f MB" % (size / (1024.0 * 1024.0))
    if size >= 1024:
        return "%.1f KB" % (size / 1024.0)
    return "%d B" % size


def _display_path(path: Path) -> str:
    """相对当前工作目录显示，统一用 / 分隔，日志更易读。"""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _load_json(path: Path, label: str) -> dict:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise BuildError("%s 不存在：%s" % (label, _display_path(path)))
    except OSError as exc:
        raise BuildError("读取 %s 失败（%s）：%s" % (label, _display_path(path), exc))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BuildError(
            "%s JSON 格式非法（%s）：第 %d 行第 %d 列 —— %s"
            % (label, _display_path(path), exc.lineno, exc.colno, exc.msg)
        )
    if not isinstance(data, dict):
        raise BuildError("%s 顶层必须是 JSON 对象：%s" % (label, _display_path(path)))
    return data


def _read_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise BuildError("%s 不存在：%s" % (label, _display_path(path)))
    except UnicodeDecodeError as exc:
        raise BuildError("%s 不是合法 UTF-8 文本（%s）：%s" % (label, _display_path(path), exc))
    except OSError as exc:
        raise BuildError("读取 %s 失败（%s）：%s" % (label, _display_path(path), exc))


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_frontmatter(text: str, label: str) -> Dict[str, str]:
    """极简 YAML frontmatter 解析：只取顶层标量字段（含 >- / | 块），不引入 PyYAML。

    仅用于校验 name/description 等少量字段；不追求完整 YAML 语义。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise BuildError("%s 缺少 YAML front matter（首行必须为 ---）" % label)
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        raise BuildError("%s 的 YAML front matter 缺少结束标记 ---" % label)

    data: Dict[str, str] = {}
    i = 1
    while i < end:
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line[0] in (" ", "\t") or ":" not in line:
            i += 1
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        value = raw_value.strip()
        if not key:
            i += 1
            continue
        if value in (">", ">-", ">+", "|", "|-", "|+"):
            block: List[str] = []
            i += 1
            while i < end:
                nxt = lines[i]
                if nxt.strip() and not nxt[0].isspace():
                    break
                block.append(nxt.strip())
                i += 1
            data[key] = " ".join(part for part in block if part).strip()
        else:
            data[key] = _unquote(value)
            i += 1
    return data


# ── 校验：PMS 接口契约 ──────────────────────────────────────────────────────────
def validate_spec(src: Path) -> dict:
    spec = _load_json(src / "spec" / "interfaces.json", "spec/interfaces.json")
    errors: List[str] = []

    tools = spec.get("tools")
    if not isinstance(tools, list):
        raise BuildError("spec/interfaces.json 缺少 tools 数组")
    if len(tools) != EXPECTED_PMS_TOOL_COUNT:
        errors.append(
            "tools 数量应为 %d，实际 %d（新增接口需同步修改 build_pack.py 的 EXPECTED_PMS_TOOL_COUNT）"
            % (EXPECTED_PMS_TOOL_COUNT, len(tools))
        )

    groups = spec.get("groups")
    if not isinstance(groups, list) or not groups:
        errors.append("缺少 groups 数组")
        groups = []
    group_ids: List[str] = []
    group_titles: Dict[str, str] = {}
    for idx, group in enumerate(groups):
        if not isinstance(group, dict):
            errors.append("groups[%d] 不是对象" % idx)
            continue
        gid = group.get("id")
        if not isinstance(gid, str) or not gid:
            errors.append("groups[%d].id 缺失" % idx)
            continue
        if gid in group_ids:
            errors.append("groups 中 id 重复：%s" % gid)
        group_ids.append(gid)
        group_titles[gid] = group.get("title") or gid
        if not group.get("skill"):
            errors.append("groups[%s].skill 缺失" % gid)
        if not group.get("role"):
            errors.append("groups[%s].role 缺失" % gid)

    names: List[str] = []
    codes: List[str] = []
    group_counts: Dict[str, int] = {}
    for idx, tool in enumerate(tools):
        where = "tools[%d]" % idx
        if not isinstance(tool, dict):
            errors.append("%s 不是对象" % where)
            continue
        name = tool.get("name")
        code = tool.get("code")
        if not isinstance(name, str) or not name:
            errors.append("%s.name 缺失" % where)
        else:
            if not NAME_PATTERN.match(name):
                errors.append("%s.name 不合法（应匹配 ^[a-z][a-z0-9_]*$）：%s" % (where, name))
            if name in names:
                errors.append("工具 name 重复：%s" % name)
            names.append(name)
        if not isinstance(code, str) or not code:
            errors.append("%s.code 缺失" % where)
        else:
            if code in codes:
                errors.append("接口编码 code 重复：%s" % code)
            codes.append(code)

        gid = tool.get("group")
        if not isinstance(gid, str) or not gid:
            errors.append("%s.group 缺失" % where)
        elif gid not in group_ids:
            errors.append("%s.group 不合法（不在 spec.groups 中）：%s" % (where, gid))
        else:
            group_counts[gid] = group_counts.get(gid, 0) + 1

        if not tool.get("title"):
            errors.append("%s.title 缺失" % where)
        method = tool.get("method")
        if method not in ("GET", "POST"):
            errors.append("%s.method 应为 GET/POST，实际：%r" % (where, method))
        path = tool.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            errors.append("%s.path 缺失或以 / 开头：%r" % (where, path))
        params = tool.get("params")
        if not isinstance(params, list) or not params:
            errors.append("%s.params 必须是非空数组" % where)
        if not isinstance(tool.get("responseHint"), dict):
            errors.append("%s.responseHint 缺失" % where)
        if not isinstance(tool.get("mock"), dict) or not tool.get("mock"):
            errors.append("%s.mock 缺失（Mock 模式数据）" % where)
        questions = tool.get("typicalQuestions")
        if not isinstance(questions, list) or not questions:
            errors.append("%s.typicalQuestions 必须是非空数组" % where)

    for group in groups:
        if not isinstance(group, dict):
            continue
        gid = group.get("id")
        if not isinstance(gid, str) or not gid:
            continue
        expected = group.get("toolCount")
        actual = group_counts.get(gid, 0)
        if not isinstance(expected, int):
            errors.append("groups[%s].toolCount 缺失或不是整数" % gid)
        elif expected != actual:
            errors.append("groups[%s].toolCount=%d，但实际工具数=%d" % (gid, expected, actual))

    defaults = spec.get("defaults")
    if isinstance(defaults, dict):
        auth_mode = defaults.get("authMode")
        auth_modes = defaults.get("authModes")
        if isinstance(auth_modes, list) and auth_mode not in auth_modes:
            errors.append("defaults.authMode=%r 不在 defaults.authModes 中" % (auth_mode,))
    else:
        errors.append("spec 缺少 defaults 配置")

    for key in ("specVersion", "packSlug", "packDisplayName"):
        if not spec.get(key):
            errors.append("spec 缺少 %s" % key)

    if errors:
        raise BuildError("spec/interfaces.json 校验失败（%d 项）：\n%s"
                         % (len(errors), "\n".join("  - " + item for item in errors)))
    return spec


# ── 校验：分析工具契约与数据包 schema ───────────────────────────────────────────
def validate_analysis_spec(src: Path) -> dict:
    """校验 spec/analysis-tools.json：7 个工具、name 唯一、参数 required 合法。"""
    spec = _load_json(src / ANALYSIS_SPEC_REL, "spec/analysis-tools.json")
    errors: List[str] = []

    for key in ("specVersion", "server", "displayName", "note"):
        value = spec.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append("spec/analysis-tools.json 缺少字段或为空：%s" % key)
    server = spec.get("server")
    if isinstance(server, str) and server.strip() and server != ANALYSIS_SKILL:
        errors.append("spec/analysis-tools.json server 应为 %s，实际 %r" % (ANALYSIS_SKILL, server))

    contract = spec.get("inputContract")
    if not isinstance(contract, str) or not contract.strip():
        errors.append("spec/analysis-tools.json 缺少 inputContract（应为 %s）" % ANALYSIS_INPUT_CONTRACT)
    elif contract != ANALYSIS_INPUT_CONTRACT:
        errors.append("inputContract 应为 %s，实际 %r" % (ANALYSIS_INPUT_CONTRACT, contract))

    tools = spec.get("tools")
    if not isinstance(tools, list):
        errors.append("spec/analysis-tools.json 缺少 tools 数组")
        tools = []
    elif len(tools) != EXPECTED_ANALYSIS_TOOL_COUNT:
        errors.append(
            "分析工具数量应为 %d，实际 %d（新增分析能力需同步修改 build_pack.py 的 "
            "EXPECTED_ANALYSIS_TOOL_COUNT，并更新 docs/01 第四节）"
            % (EXPECTED_ANALYSIS_TOOL_COUNT, len(tools))
        )

    names: List[str] = []
    for idx, tool in enumerate(tools):
        where = "tools[%d]" % idx
        if not isinstance(tool, dict):
            errors.append("%s 不是对象" % where)
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            errors.append("%s.name 缺失" % where)
        else:
            if not NAME_PATTERN.match(name):
                errors.append("%s.name 不合法（应匹配 ^[a-z][a-z0-9_]*$）：%s" % (where, name))
            if name in names:
                errors.append("分析工具 name 重复：%s" % name)
            names.append(name)

        for key in ("title", "desc", "returns"):
            value = tool.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append("%s.%s 缺失或为空" % (where, key))

        params = tool.get("params")
        if not isinstance(params, list):
            errors.append("%s.params 必须是数组（可为空数组）" % where)
            continue
        param_names: List[str] = []
        seen_optional = False
        for pidx, param in enumerate(params):
            pwhere = "%s.params[%d]" % (where, pidx)
            if not isinstance(param, dict):
                errors.append("%s 不是对象" % pwhere)
                continue
            pname = param.get("name")
            if not isinstance(pname, str) or not pname:
                errors.append("%s.name 缺失" % pwhere)
            else:
                if not NAME_PATTERN.match(pname):
                    errors.append("%s.name 不合法（应匹配 ^[a-z][a-z0-9_]*$）：%s" % (pwhere, pname))
                if pname in param_names:
                    errors.append("%s 参数 name 重复：%s" % (where, pname))
                param_names.append(pname)

            ptype = param.get("type")
            if not isinstance(ptype, str) or not ptype:
                errors.append("%s.type 缺失" % pwhere)
            elif ptype not in VALID_PARAM_TYPES:
                errors.append("%s.type 不合法：%r（可选值：%s）"
                              % (pwhere, ptype, "、".join(sorted(VALID_PARAM_TYPES))))

            required = param.get("required")
            if not isinstance(required, bool):
                errors.append("%s.required 必须是布尔值 true/false，实际：%r" % (pwhere, required))
                required = None
            elif required:
                if seen_optional:
                    errors.append("%s.required=true 必须排在所有可选参数之前" % pwhere)
                if "default" in param:
                    errors.append("%s.required=true 的参数不应带 default（契约自洽性）" % pwhere)
            else:
                seen_optional = True

            if "desc" in param and not (isinstance(param.get("desc"), str) and param.get("desc").strip()):
                errors.append("%s.desc 不能为空字符串" % pwhere)

            enum = param.get("enum")
            if enum is not None:
                if not isinstance(enum, list) or not enum:
                    errors.append("%s.enum 必须是非空数组" % pwhere)
                else:
                    for item in enum:
                        if not isinstance(item, str) or not item:
                            errors.append("%s.enum 只能包含非空字符串：%r" % (pwhere, item))

    design_rules = spec.get("designRules")
    if not isinstance(design_rules, list) or not design_rules:
        errors.append("spec/analysis-tools.json 缺少 designRules 非空数组")
    else:
        for idx, rule in enumerate(design_rules):
            if not isinstance(rule, str) or not rule.strip():
                errors.append("designRules[%d] 必须是非空字符串" % idx)

    if errors:
        raise BuildError("spec/analysis-tools.json 校验失败（%d 项）：\n%s"
                         % (len(errors), "\n".join("  - " + item for item in errors)))
    return spec


def validate_analysis_bundle_schema(src: Path) -> dict:
    """校验 spec/analysis-bundle.schema.json：合法 JSON 且具备最小契约结构。"""
    schema = _load_json(src / ANALYSIS_BUNDLE_SCHEMA_REL, "spec/analysis-bundle.schema.json")
    errors: List[str] = []

    schema_uri = schema.get("$schema")
    if not isinstance(schema_uri, str) or "json-schema" not in schema_uri:
        errors.append("缺少 $schema（应指向 JSON Schema 规范，如 draft 2020-12）")
    schema_id = schema.get("$id")
    if not isinstance(schema_id, str) or not schema_id.strip():
        errors.append("缺少 $id")
    for key in ("title", "description"):
        value = schema.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append("缺少 %s" % key)

    if schema.get("type") != "object":
        errors.append("根节点 type 必须为 object，实际：%r" % (schema.get("type"),))

    required = schema.get("required")
    if not isinstance(required, list) or "device" not in required:
        errors.append("根 required 必须包含 device（设备基本信息是唯一必填段）")

    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        errors.append("缺少 properties 对象或为空")
        properties = {}
    device = properties.get("device")
    if not isinstance(device, dict):
        errors.append("properties.device 缺失或不是对象")
    else:
        if device.get("type") != "object":
            errors.append("properties.device.type 必须为 object")
        device_required = device.get("required")
        if not isinstance(device_required, list) or "name" not in device_required:
            errors.append("properties.device.required 必须包含 name")
        device_props = device.get("properties")
        if not isinstance(device_props, dict) or "name" not in device_props:
            errors.append("properties.device.properties 必须定义 name")

    if errors:
        raise BuildError("spec/analysis-bundle.schema.json 校验失败（%d 项）：\n%s"
                         % (len(errors), "\n".join("  - " + item for item in errors)))
    return schema


def validate_analysis_assets(src: Path) -> None:
    """校验分析引擎技能目录内的契约资产（打包前尽早暴露缺文件问题）。

    技能目录本身不存在时跳过：是否缺技能由 validate_skills / --allow-missing 决定。
    """
    skill_dir = src / "skills" / ANALYSIS_SKILL
    if not skill_dir.is_dir():
        return

    errors: List[str] = []
    for arcname in ANALYSIS_REQUIRED_ARCNAMES:
        if not (skill_dir / arcname).is_file():
            errors.append("缺少 %s（%s 发布包必备资产）" % (arcname, ANALYSIS_SKILL))

    parsed: Dict[str, object] = {}
    for arcname in ANALYSIS_JSON_ARCNAMES:
        path = skill_dir / arcname
        if not path.is_file():
            continue
        try:
            parsed[arcname] = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            errors.append("%s 不是合法 UTF-8 JSON 文件（%s）" % (arcname, exc))

    demo = parsed.get("assets/demo_bundle.json")
    if demo is not None:
        if not isinstance(demo, dict):
            errors.append("assets/demo_bundle.json 顶层必须是 JSON 对象（bundle）")
        else:
            device = demo.get("device")
            if not isinstance(device, dict) or not device.get("name"):
                errors.append("assets/demo_bundle.json 必须符合 bundle schema：device.name 必填"
                              "（见 spec/analysis-bundle.schema.json）")

    if errors:
        raise BuildError("分析引擎资产校验失败（%d 项）：\n%s"
                         % (len(errors), "\n".join("  - " + item for item in errors)))


# ── 校验：manifest / identify / skills ─────────────────────────────────────────
def validate_manifest(src: Path, spec: dict) -> dict:
    manifest = _load_json(src / "manifest.json", "manifest.json")
    errors: List[str] = []

    for key in ("manifestVersion", "type", "slug", "displayName", "summary"):
        if not isinstance(manifest.get(key), str) or not manifest.get(key).strip():
            errors.append("manifest 缺少字段：%s" % key)
    if isinstance(manifest.get("manifestVersion"), str) and manifest["manifestVersion"].strip() != MANIFEST_VERSION:
        errors.append("manifest.manifestVersion 应为 %r（平台清单版本），实际 %r"
                      % (MANIFEST_VERSION, manifest.get("manifestVersion")))
    if isinstance(manifest.get("type"), str) and manifest["type"].strip() != MANIFEST_TYPE:
        errors.append("manifest.type 应为 %r（平台 SkillSet 类型），实际 %r"
                      % (MANIFEST_TYPE, manifest.get("type")))
    for key in ("scene", "subScene"):
        if key in manifest and manifest[key] is not None and not isinstance(manifest[key], str):
            errors.append("manifest.%s 若提供必须是字符串" % key)
    slug = manifest.get("slug")
    if isinstance(slug, str) and slug and spec.get("packSlug") and slug != spec.get("packSlug"):
        errors.append("manifest.slug=%r 与 spec.packSlug=%r 不一致" % (slug, spec.get("packSlug")))
    if isinstance(manifest.get("displayName"), str) and spec.get("packDisplayName") \
            and manifest["displayName"] != spec["packDisplayName"]:
        errors.append("manifest.displayName 与 spec.packDisplayName 不一致：%r != %r"
                      % (manifest["displayName"], spec["packDisplayName"]))

    skill_slugs = manifest.get("skillSlugs")
    if not isinstance(skill_slugs, list) or not skill_slugs:
        errors.append("manifest.skillSlugs 必须是非空数组")
        skill_slugs = []
    else:
        seen = set()
        for item in skill_slugs:
            if not isinstance(item, str) or not item:
                errors.append("manifest.skillSlugs 含非字符串或空值：%r" % (item,))
                continue
            if not SLUG_PATTERN.match(item):
                errors.append("skillSlugs 不合法（应匹配 ^[a-z0-9][a-z0-9-]*$）：%s" % item)
            if item in seen:
                errors.append("manifest.skillSlugs 重复：%s" % item)
            seen.add(item)
        # 顺序契约：两个底座在最前（pms 数据底座 → analysis 分析底座），问数总控在最后
        if len(skill_slugs) >= len(BASE_SKILL_SLUGS):
            head = tuple(item for item in skill_slugs[:len(BASE_SKILL_SLUGS)] if isinstance(item, str))
            if head != BASE_SKILL_SLUGS:
                errors.append("manifest.skillSlugs 前 %d 项必须是底座技能 %s，实际 %s"
                              % (len(BASE_SKILL_SLUGS), " → ".join(BASE_SKILL_SLUGS),
                                 " → ".join(head) if head else "（空）"))
        tail = skill_slugs[-1] if skill_slugs else None
        if tail != ORCHESTRATOR_SKILL:
            errors.append("manifest.skillSlugs 最后一项必须是总控技能 %s，实际 %r"
                          % (ORCHESTRATOR_SKILL, tail))
        if ORCHESTRATOR_SKILL not in skill_slugs:
            errors.append("manifest.skillSlugs 缺少总控技能 %s" % ORCHESTRATOR_SKILL)
        if ANALYSIS_SKILL not in skill_slugs:
            errors.append("manifest.skillSlugs 缺少分析底座技能 %s" % ANALYSIS_SKILL)

    identify = src / "identify.md"
    if not identify.is_file():
        errors.append("缺少 identify.md（平台安装格式必需）：%s" % _display_path(identify))
    else:
        identify_text = _read_text(identify, "identify.md")
        try:
            meta = _parse_frontmatter(identify_text, "identify.md")
        except BuildError as exc:
            errors.append(str(exc))
        else:
            name = (meta.get("name") or "").strip()
            if not name:
                errors.append("identify.md frontmatter 缺少 name（应为专家包 slug）")
            elif isinstance(slug, str) and name != slug:
                errors.append("identify.md frontmatter name=%r 与 manifest.slug=%r 不一致" % (name, slug))
            if not (meta.get("description") or "").strip():
                errors.append("identify.md frontmatter 缺少 description")
            identify_version = (meta.get("version") or "").strip()
            if not identify_version:
                errors.append("identify.md frontmatter 缺少 version（发布版本号）")
            elif not SEMVER_PATTERN.match(identify_version):
                errors.append("identify.md frontmatter version=%r 不是 SemVer（如 1.1.0）"
                              % identify_version)

    if errors:
        raise BuildError("manifest.json / identify.md 校验失败（%d 项）：\n%s"
                         % (len(errors), "\n".join("  - " + item for item in errors)))
    return manifest


def validate_skills(src: Path, slugs: List[str]) -> Tuple[List[str], List[str]]:
    """返回 (可用于打包的 slug 列表, 缺失说明列表)。

    - 缺失（目录或 SKILL.md 不存在）允许在 --allow-missing 时跳过；
    - frontmatter 非法 / name 不一致属于结构错误，始终失败。
    """
    skills_root = src / "skills"
    usable: List[str] = []
    missing: List[str] = []
    invalid: List[str] = []

    for slug in slugs:
        skill_dir = skills_root / slug
        if not skill_dir.is_dir():
            missing.append("%s：目录不存在（%s）" % (slug, _display_path(skill_dir)))
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            missing.append("%s：缺少 SKILL.md（%s）" % (slug, _display_path(skill_md)))
            continue
        try:
            text = _read_text(skill_md, "skills/%s/SKILL.md" % slug)
            meta = _parse_frontmatter(text, "skills/%s/SKILL.md" % slug)
        except BuildError as exc:
            invalid.append(str(exc))
            continue
        name = (meta.get("name") or "").strip()
        if not name:
            invalid.append("skills/%s/SKILL.md frontmatter 缺少 name（应为 %s）" % (slug, slug))
            continue
        if name != slug:
            invalid.append("skills/%s/SKILL.md frontmatter name=%r，与目录名 %r 不一致"
                           % (slug, name, slug))
            continue
        if not (meta.get("description") or "").strip():
            invalid.append("skills/%s/SKILL.md frontmatter 缺少 description" % slug)
            continue
        meta_slug = (meta.get("slug") or "").strip()
        if not meta_slug:
            invalid.append("skills/%s/SKILL.md frontmatter 缺少 slug（skillhub publish 必填）" % slug)
            continue
        if meta_slug != slug:
            invalid.append("skills/%s/SKILL.md frontmatter slug=%r，与目录名 %r 不一致"
                           % (slug, meta_slug, slug))
            continue
        if not (meta.get("displayName") or "").strip():
            invalid.append("skills/%s/SKILL.md frontmatter 缺少 displayName（skillhub publish 必填）" % slug)
            continue
        meta_version = (meta.get("version") or "").strip()
        if not meta_version:
            invalid.append("skills/%s/SKILL.md frontmatter 缺少 version（发布版本号）" % slug)
            continue
        if not SEMVER_PATTERN.match(meta_version):
            invalid.append("skills/%s/SKILL.md frontmatter version=%r 不是 SemVer（如 1.1.0）"
                           % (slug, meta_version))
            continue
        usable.append(slug)

    if invalid:
        raise BuildError("技能结构校验失败（%d 项）：\n%s"
                         % (len(invalid), "\n".join("  - " + item for item in invalid)))
    return usable, missing


# ── zip 打包（确定性输出） ────────────────────────────────────────────────────────
def _write_zip(dest: Path, entries: List[Tuple[str, bytes]]) -> None:
    """按给定顺序写入 zip；固定时间戳与 unix 权限位，保证可重复构建。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        with zipfile.ZipFile(str(tmp), "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for arcname, data in entries:
                info = zipfile.ZipInfo(filename=arcname, date_time=FIXED_ZIP_DATE)
                info.create_system = 3  # unix，解压时不携带 Windows ACL
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o644 & 0xFFFF) << 16
                zf.writestr(info, data)
        os.replace(str(tmp), str(dest))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _check_zip_size(path: Path) -> None:
    size = path.stat().st_size
    if size >= MAX_ZIP_BYTES:
        raise BuildError("zip 体积超限：%s 为 %s，超过平台单包上限 %d MB"
                         % (_display_path(path), _fmt_size(size), PACK_ZIP_LIMIT_MB))


def _verify_skill_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(str(path)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        raise BuildError("生成的 zip 无法读取：%s（%s）" % (_display_path(path), exc))
    if "SKILL.md" not in names:
        raise BuildError("技能包根目录缺少 SKILL.md：%s" % _display_path(path))
    for name in names:
        if name.startswith("/") or ".." in Path(name).parts or "\\" in name:
            raise BuildError("技能包内含非法路径：%s（%s）" % (name, _display_path(path)))


def _verify_spec_snapshot(path: Path, slug: str, spec_bytes: bytes) -> None:
    """校验底座 zip 内置 spec 快照且与 spec 文件字节一致；其余技能不得包含该文件。"""
    try:
        with zipfile.ZipFile(str(path)) as zf:
            names = zf.namelist()
            snapshot: Optional[bytes] = None
            has_snapshot = SPEC_SNAPSHOT_ARCNAME in names
            if slug == SPEC_SNAPSHOT_SKILL and has_snapshot:
                snapshot = zf.read(SPEC_SNAPSHOT_ARCNAME)
    except zipfile.BadZipFile as exc:
        raise BuildError("生成的 zip 无法读取：%s（%s）" % (_display_path(path), exc))

    if slug != SPEC_SNAPSHOT_SKILL:
        if has_snapshot:
            raise BuildError("非底座技能不应包含 spec 快照：%s（%s）"
                             % (_display_path(path), SPEC_SNAPSHOT_ARCNAME))
        return

    if not has_snapshot or snapshot is None:
        raise BuildError("底座技能 zip 缺少内置 spec 快照：%s（%s）"
                         % (_display_path(path), SPEC_SNAPSHOT_ARCNAME))
    if snapshot != spec_bytes:
        raise BuildError("底座技能内置 spec 快照与 spec/interfaces.json 字节不一致（%s，"
                         "快照 %d 字节 / spec %d 字节）"
                         % (_display_path(path), len(snapshot), len(spec_bytes)))


def _verify_analysis_assets(path: Path, slug: str) -> None:
    """分析底座 zip 必须内置契约资产；其余技能不得包含这些文件（防止误打包）。"""
    try:
        with zipfile.ZipFile(str(path)) as zf:
            names = set(zf.namelist())
            if slug != ANALYSIS_SKILL:
                forbidden = sorted(set(ANALYSIS_REQUIRED_ARCNAMES) & names)
                if forbidden:
                    raise BuildError("非分析引擎技能不应包含分析引擎资产（%s）：%s"
                                     % (_display_path(path), "、".join(forbidden)))
                return
            missing = [arc for arc in ANALYSIS_REQUIRED_ARCNAMES if arc not in names]
            if missing:
                raise BuildError("分析引擎 zip 缺少契约资产（%s）：%s"
                                 % (_display_path(path), "、".join(missing)))
            for arcname in ANALYSIS_JSON_ARCNAMES:
                try:
                    json.loads(zf.read(arcname).decode("utf-8-sig"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise BuildError("分析引擎 zip 内 %s 不是合法 UTF-8 JSON（%s）：%s"
                                     % (arcname, exc, _display_path(path)))
    except zipfile.BadZipFile as exc:
        raise BuildError("生成的 zip 无法读取：%s（%s）" % (_display_path(path), exc))


def _skill_summary(meta: dict, limit: int = 120) -> str:
    """把技能 description 压成单行摘要（平台清单 skills[].summary 用）。"""
    text = re.sub(r"\s+", " ", (meta.get("description") or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def collect_skill_briefs(src: Path, slugs: List[str]) -> List[dict]:
    """从各技能 SKILL.md frontmatter 生成平台清单的 skills[] 数组。"""
    briefs: List[dict] = []
    for slug in slugs:
        skill_md = src / "skills" / slug / "SKILL.md"
        text = _read_text(skill_md, "skills/%s/SKILL.md" % slug)
        meta = _parse_frontmatter(text, "skills/%s/SKILL.md" % slug)
        briefs.append({
            "slug": slug,
            "displayName": (meta.get("displayName") or "").strip(),
            "summary": _skill_summary(meta),
        })
    return briefs


def build_bundle_manifest(manifest: dict, skill_briefs: List[dict], identify_bytes: bytes) -> bytes:
    """生成平台专家包清单（manifest.json）：作者字段 + 构建生成的 skills[]/files[]。"""
    bundle: Dict[str, object] = {
        "manifestVersion": MANIFEST_VERSION,
        "type": MANIFEST_TYPE,
        "slug": manifest["slug"],
        "displayName": manifest["displayName"],
        "summary": manifest["summary"],
    }
    for key in ("scene", "subScene"):
        value = manifest.get(key)
        if isinstance(value, str) and value.strip():
            bundle[key] = value.strip()
    bundle["skillSlugs"] = list(manifest["skillSlugs"])
    bundle["skills"] = skill_briefs
    bundle["files"] = [{
        "path": BUNDLE_IDENTIFY_NAME,
        "sha256": _sha256(identify_bytes),
        "size": len(identify_bytes),
    }]
    return (json.dumps(bundle, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _verify_bundle_zip(path: Path, pack_slug: str,
                       manifest_bytes: bytes, identify_bytes: bytes) -> None:
    """校验专家包清单包：仅两个条目，且 manifest.files[] 与 identify.md 字节一致。"""
    try:
        with zipfile.ZipFile(str(path)) as zf:
            names = zf.namelist()
            manifest_in = zf.read(BUNDLE_MANIFEST_NAME)
            identify_in = zf.read(BUNDLE_IDENTIFY_NAME)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise BuildError("生成的专家包清单 zip 无法读取：%s（%s）"
                         % (_display_path(path), exc))
    if set(names) != {BUNDLE_MANIFEST_NAME, BUNDLE_IDENTIFY_NAME}:
        raise BuildError("专家包清单 zip 只应包含 %s 与 %s（%s），实际：%s"
                         % (BUNDLE_MANIFEST_NAME, BUNDLE_IDENTIFY_NAME,
                            _display_path(path), "、".join(sorted(names))))
    if manifest_in != manifest_bytes:
        raise BuildError("专家包清单 zip 内的 manifest.json 与构建生成内容不一致：%s"
                         % _display_path(path))
    if identify_in != identify_bytes:
        raise BuildError("专家包清单 zip 内的 identify.md 与源文件不一致：%s"
                         % _display_path(path))
    try:
        data = json.loads(manifest_in.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BuildError("专家包清单 manifest.json 不是合法 UTF-8 JSON：%s（%s）"
                         % (_display_path(path), exc))
    if data.get("type") != MANIFEST_TYPE or data.get("slug") != pack_slug:
        raise BuildError("专家包清单 type/slug 不正确：%s（type=%r, slug=%r）"
                         % (_display_path(path), data.get("type"), data.get("slug")))
    files = data.get("files")
    if not isinstance(files, list) or len(files) != 1:
        raise BuildError("专家包清单 files[] 必须恰好包含 identify.md 一项：%s"
                         % _display_path(path))
    entry = files[0]
    if (entry.get("path") != BUNDLE_IDENTIFY_NAME
            or entry.get("sha256") != _sha256(identify_bytes)
            or entry.get("size") != len(identify_bytes)):
        raise BuildError("专家包清单 files[] 与 identify.md 字节不一致（sha256/size）：%s"
                         % _display_path(path))
    skills = data.get("skills")
    slugs = data.get("skillSlugs")
    if not isinstance(skills, list) or not isinstance(slugs, list):
        raise BuildError("专家包清单缺少 skills[]/skillSlugs[]：%s" % _display_path(path))
    if [item.get("slug") for item in skills if isinstance(item, dict)] != slugs:
        raise BuildError("专家包清单 skills[] 与 skillSlugs[] 顺序不一致：%s"
                         % _display_path(path))


def _collect_skill_files(skill_dir: Path, exclude_roots: List[Path]) -> List[Tuple[str, bytes]]:
    """收集技能目录下的文件，返回 (zip 内相对路径, 内容)，按路径排序。"""
    skill_dir = skill_dir.resolve()
    exclude_resolved = [item.resolve() for item in exclude_roots]
    collected: List[Tuple[str, bytes]] = []
    for root, dirs, files in os.walk(str(skill_dir), followlinks=False):
        root_path = Path(root)
        pruned: List[str] = []
        for dirname in dirs:
            if dirname in EXCLUDE_DIR_NAMES:
                continue
            dir_path = (root_path / dirname).resolve()
            if any(dir_path == ex or ex in dir_path.parents for ex in exclude_resolved):
                continue
            pruned.append(dirname)
        dirs[:] = sorted(pruned)
        for fname in sorted(files):
            if fname in EXCLUDE_FILE_NAMES or fname.lower().endswith(EXCLUDE_FILE_SUFFIXES):
                continue
            abs_path = root_path / fname
            if abs_path.is_symlink():
                print("警告：跳过软连接（不打包）：%s" % _display_path(abs_path), file=sys.stderr)
                continue
            rel = abs_path.relative_to(skill_dir).as_posix()
            try:
                data = abs_path.read_bytes()
            except OSError as exc:
                raise BuildError("读取文件失败：%s（%s）" % (_display_path(abs_path), exc))
            collected.append((rel, data))
    collected.sort(key=lambda item: item[0])
    return collected


# ── 构建主流程 ──────────────────────────────────────────────────────────────────
def _resolve_paths(src_arg: str, out_arg: str) -> Tuple[Path, Path]:
    cwd = Path.cwd()
    script_pack_root = Path(__file__).resolve().parent.parent

    src = Path(src_arg)
    if not src.is_absolute():
        src = cwd / src
    if not src.is_dir():
        # 兼容从任意目录直接执行脚本：回退到脚本所在的 expert-pack 目录
        if not src_arg or src_arg == "expert-pack":
            src = script_pack_root
        if not src.is_dir():
            raise BuildError("源目录不存在：%s" % _display_path(src))
    src = src.resolve()

    if out_arg:
        out = Path(out_arg)
        if not out.is_absolute():
            out = cwd / out
    else:
        out = src / "dist"
    out = out.resolve()

    if out == src:
        raise BuildError("输出目录不能等于源目录：%s" % _display_path(out))
    if out in src.parents:
        raise BuildError("输出目录不能是源目录的上级：%s" % _display_path(out))
    if out == (src / "skills").resolve():
        raise BuildError("输出目录不能是源目录下的 skills 目录（会覆盖源码）：%s" % _display_path(out))
    if out.parent == out:
        raise BuildError("输出目录不能是文件系统根目录：%s" % _display_path(out))
    for name in (BASE_SKILL_SLUGS[0], ANALYSIS_SKILL):
        skill_dir = (src / "skills" / name).resolve()
        if out == skill_dir or skill_dir in out.parents:
            raise BuildError("输出目录不能位于技能目录内部（会污染技能包）：%s" % _display_path(out))
    return src, out


def _clean_artifacts(out: Path, pack_slug: str) -> None:
    """只清理本脚本生成的产物，保留目录内其他文件；保证可重复运行。"""
    skills_out = out / "skills"
    if skills_out.is_dir():
        shutil.rmtree(str(skills_out))
    elif skills_out.exists():
        skills_out.unlink()
    for name in (pack_slug + ".zip", pack_slug + "-install.zip",
                 pack_slug + "-bundle.zip", "checksums.txt"):
        target = out / name
        if target.is_file():
            target.unlink()
    out.mkdir(parents=True, exist_ok=True)
    skills_out.mkdir(parents=True, exist_ok=True)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(args: argparse.Namespace) -> int:
    src, out = _resolve_paths(args.src, args.out)

    print("== 变电智能问数专家包 · 构建与校验 ==")
    print("源目录：%s" % _display_path(src))
    print("输出目录：%s" % _display_path(out))

    spec = validate_spec(src)
    analysis_spec = validate_analysis_spec(src)
    validate_analysis_bundle_schema(src)
    manifest = validate_manifest(src, spec)
    pack_slug = manifest["slug"]
    skill_slugs = list(manifest["skillSlugs"])

    usable, missing = validate_skills(src, skill_slugs)
    validate_analysis_assets(src)
    skill_briefs = collect_skill_briefs(src, usable)

    pms_tool_count = len(spec["tools"])
    analysis_tool_count = len(analysis_spec["tools"])
    print("校验通过：PMS spec %d 个工具（name/code 唯一、group 合法）；"
          "分析 spec %d 个工具（name 唯一、required 合法）；bundle schema 合法；"
          "manifest 与 spec 一致；技能清单 %d 个（顺序：%s … %s）。"
          % (pms_tool_count, analysis_tool_count, len(skill_slugs),
             skill_slugs[0] if skill_slugs else "-", skill_slugs[-1] if skill_slugs else "-"))
    spec_bytes = (src / "spec" / "interfaces.json").read_bytes()
    print("底座 spec 快照：%s 的发布 zip 将内置 %s（内容=spec/interfaces.json，%d 字节）。"
          % (SPEC_SNAPSHOT_SKILL, SPEC_SNAPSHOT_ARCNAME, len(spec_bytes)))
    print("分析引擎资产：%s 的发布 zip 将内置 %d 个契约文件（评分卡/规则库/3 个报告模板/demo 数据包）。"
          % (ANALYSIS_SKILL, len(ANALYSIS_REQUIRED_ARCNAMES)))
    if missing:
        detail = "\n".join("  - " + item for item in missing)
        if not args.allow_missing:
            raise BuildError(
                "技能不完整：manifest 共 %d 个技能，仅 %d 个就绪，缺少 %d 个：\n%s\n"
                "请等待技能编写完成后重试。如需临时验证打包流程，可加 --allow-missing"
                "（产物仅供本地验证，禁止用于正式发布）。"
                % (len(skill_slugs), len(usable), len(missing), detail)
            )
        print("警告：技能不完整（%d/%d 就绪），仅打包已有技能；产物不得用于正式发布：\n%s"
              % (len(usable), len(skill_slugs), detail), file=sys.stderr)

    if args.validate_only:
        print("校验完成：未生成任何产物（--validate-only）。")
        return 0

    _clean_artifacts(out, pack_slug)

    identify_bytes = (src / "identify.md").read_bytes()
    artifacts: List[Tuple[Path, int, str]] = []  # (路径, 大小, sha256)

    # 1) 技能 zip：zip 根即技能根；PMS 底座注入 spec 快照；分析底座校验契约资产
    skill_zip_names: List[str] = []
    for slug in usable:
        skill_dir = src / "skills" / slug
        entries = _collect_skill_files(skill_dir, exclude_roots=[out])
        if not any(arc.lower() == "skill.md" for arc, _ in entries):
            raise BuildError("技能 %s 打包后根目录缺少 SKILL.md" % slug)
        if slug == SPEC_SNAPSHOT_SKILL:
            # 注入构建生成件：内容 = spec/interfaces.json 原始字节（固定时间戳，确定性）
            entries = [item for item in entries if item[0] != SPEC_SNAPSHOT_ARCNAME]
            entries.append((SPEC_SNAPSHOT_ARCNAME, spec_bytes))
            entries.sort(key=lambda item: item[0])
        dest = out / "skills" / (slug + ".zip")
        _write_zip(dest, entries)
        _verify_skill_zip(dest)
        _verify_spec_snapshot(dest, slug, spec_bytes)
        _verify_analysis_assets(dest, slug)
        _check_zip_size(dest)
        size = dest.stat().st_size
        artifacts.append((dest, size, _sha256(dest.read_bytes())))
        skill_zip_names.append(slug)

    # 2) 平台专家包清单包：构建生成的 manifest.json + identify.md（不含子技能 zip）
    bundle_manifest_bytes = build_bundle_manifest(manifest, skill_briefs, identify_bytes)
    bundle_zip = out / (pack_slug + "-bundle.zip")
    _write_zip(bundle_zip, [
        (BUNDLE_MANIFEST_NAME, bundle_manifest_bytes),
        (BUNDLE_IDENTIFY_NAME, identify_bytes),
    ])
    _verify_bundle_zip(bundle_zip, pack_slug, bundle_manifest_bytes, identify_bytes)
    _check_zip_size(bundle_zip)
    artifacts.append((bundle_zip, bundle_zip.stat().st_size, _sha256(bundle_zip.read_bytes())))

    # 4) checksums.txt（sha256 + 相对路径，按路径排序）
    artifacts.sort(key=lambda item: item[0].relative_to(out).as_posix())
    lines = []
    for path, size, digest in artifacts:
        rel = path.relative_to(out).as_posix()
        lines.append("%s  %s" % (digest, rel))
    checksums = out / "checksums.txt"
    with open(str(checksums), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")

    # 5) stdout 打包清单
    print("\n打包清单（输出目录：%s）：" % _display_path(out))
    print("  %-52s %10s  %s" % ("文件（相对 dist）", "大小", "sha256（前 16 位）"))
    print("  " + "-" * 92)
    for path, size, digest in artifacts:
        rel = path.relative_to(out).as_posix()
        print("  %-52s %10s  %s…" % (rel, _fmt_size(size), digest[:16]))
    print("  " + "-" * 92)
    print("  %-52s %10s" % ("checksums.txt", _fmt_size(checksums.stat().st_size)))
    print("\n完成：%d 个技能包 + 1 个专家包清单包 + checksums.txt。" % len(skill_zip_names))
    print("说明：dist/%s-bundle.zip = 平台专家包清单包（构建生成的 manifest.json + identify.md，"
          "不含子技能 zip；与 skillhub.cn 实际下载物一致）。" % pack_slug)
    print("说明：dist/skills/%s.zip 已内置 %s（spec 快照），单独安装后无需 PMS_SPEC_PATH。"
          % (SPEC_SNAPSHOT_SKILL, SPEC_SNAPSHOT_ARCNAME))
    print("说明：dist/skills/%s.zip 已内置 config/scorecard.json、config/diagnosis_rules.json、"
          "templates/*.md（3 个）、assets/demo_bundle.json，单独安装后可跑 analysis_cli.py demo。"
          % ANALYSIS_SKILL)
    if missing:
        print("警告：本次为不完整构建（%d/%d 技能），禁止用于正式发布。"
              % (len(usable), len(skill_slugs)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_pack.py",
        description=("变电智能问数专家包：校验 PMS/分析契约、平台清单与技能 frontmatter，"
                     "并生成 12 个技能包与 1 个平台专家包清单包。"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python expert-pack/tools/build_pack.py\n"
            "  python expert-pack/tools/build_pack.py --src expert-pack --out expert-pack/dist\n"
            "  python expert-pack/tools/build_pack.py --validate-only\n"
            "  python expert-pack/tools/build_pack.py --allow-missing   # 仅供本地验证\n"
        ),
    )
    parser.add_argument("--src", default="expert-pack",
                        help="专家包源目录（默认：./expert-pack；不存在时回退到脚本所在目录的上级）")
    parser.add_argument("--out", default="",
                        help="产物输出目录（默认：<src>/dist，即 expert-pack/dist）")
    parser.add_argument("--validate-only", action="store_true",
                        help="只做校验，不生成任何产物")
    parser.add_argument("--allow-missing", action="store_true",
                        help="技能未齐全时仅打包已就绪技能（产物仅供本地验证，禁止正式发布）")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    _setup_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except BuildError as exc:
        print("\n构建失败：%s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        return 1
    except Exception as exc:  # 兜底：打印堆栈便于定位，同时给中文提示
        traceback.print_exc()
        print("\n构建失败（未预期异常）：%s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
