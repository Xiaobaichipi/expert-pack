#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析引擎配置与通用工具。

职责
----
- 定位技能目录（``scripts/analysis/config.py`` 向上两级即技能根目录）；
- 加载 ``config/scorecard.json``（评分卡）与 ``config/diagnosis_rules.json``（诊断规则库）；
- 提供日期解析、半进位取整、数值格式化等**确定性**工具函数；
- 定义分析引擎统一异常类型（供 MCP / CLI 映射错误码与退出码）。

约束
----
纯标准库、无网络、无凭证；除 ``report`` 模块的 ``generatedAt`` 外不读取系统时钟，
所有时间判断以 ``bundle.timeWindow.end`` 或调用方显式传入的 ``as_of`` 为基准。
"""

from __future__ import annotations

import copy
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "SKILL_DIR",
    "CONFIG_DIR",
    "TEMPLATES_DIR",
    "ASSETS_DIR",
    "SCORECARD_PATH",
    "DIAGNOSIS_RULES_PATH",
    "AnalysisError",
    "BundleError",
    "ConfigError",
    "ReportError",
    "load_scorecard",
    "load_diagnosis_rules",
    "available_scorecard_profiles",
    "parse_date",
    "round_half_up",
    "clamp",
    "format_number",
    "read_json_file",
]

#: 技能根目录：expert-pack/skills/substation-analysis-mcp
SKILL_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = SKILL_DIR / "config"
TEMPLATES_DIR = SKILL_DIR / "templates"
ASSETS_DIR = SKILL_DIR / "assets"
REFERENCES_DIR = SKILL_DIR / "references"

SCORECARD_PATH = CONFIG_DIR / "scorecard.json"
DIAGNOSIS_RULES_PATH = CONFIG_DIR / "diagnosis_rules.json"


# ---------------------------------------------------------------------------
# 异常类型（MCP 映射为 tools/call 的 isError 信封；CLI 映射为退出码）
# ---------------------------------------------------------------------------
class AnalysisError(Exception):
    """分析引擎错误基类。"""

    code = "ANALYSIS_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


class BundleError(AnalysisError):
    """输入数据包（bundle）不合法或关键字段缺失。"""

    code = "BUNDLE_INVALID"


class ConfigError(AnalysisError):
    """评分卡 / 规则库配置不合法。"""

    code = "CONFIG_INVALID"


class ReportError(AnalysisError):
    """报告类型 / 负载（payload）不合法。"""

    code = "REPORT_INVALID"


# ---------------------------------------------------------------------------
# JSON 加载
# ---------------------------------------------------------------------------
def read_json_file(path: str | Path) -> Any:
    """读取 UTF-8 JSON 文件；失败时抛出带路径的 ConfigError。"""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {file_path}：{exc}") from None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ConfigError(f"配置文件 {file_path} 不是合法 JSON：{exc}") from None


@lru_cache(maxsize=None)
def _read_json_cached(path_str: str) -> Any:
    return read_json_file(path_str)


def _load_json_copy(path: Path) -> Any:
    # 缓存解析结果，返回深拷贝，避免调用方修改缓存内容
    return copy.deepcopy(_read_json_cached(str(path)))


def available_scorecard_profiles() -> list[str]:
    data = _load_json_copy(SCORECARD_PATH)
    profiles = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(profiles, dict) or not profiles:
        raise ConfigError(f"评分卡 {SCORECARD_PATH} 缺少 profiles 配置")
    return list(profiles.keys())


def load_scorecard(profile: str = "default") -> dict[str, Any]:
    """加载指定档位的评分卡（返回深拷贝，可安全修改）。"""
    data = _load_json_copy(SCORECARD_PATH)
    profiles = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(profiles, dict) or not profiles:
        raise ConfigError(f"评分卡 {SCORECARD_PATH} 缺少 profiles 配置")
    if profile not in profiles:
        raise ConfigError(
            f"未知评分卡档位 {profile!r}，可用档位：" + "、".join(profiles.keys())
        )
    card = profiles[profile]
    if not isinstance(card, dict):
        raise ConfigError(f"评分卡档位 {profile!r} 必须是对象")
    _validate_scorecard(card, profile)
    return card


def _validate_scorecard(card: dict[str, Any], profile: str) -> None:
    dimensions = card.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise ConfigError(f"评分卡档位 {profile!r} 缺少 dimensions")
    total_weight = 0.0
    seen: set[str] = set()
    for dim in dimensions:
        if not isinstance(dim, dict) or not dim.get("id"):
            raise ConfigError(f"评分卡档位 {profile!r} 存在缺少 id 的维度")
        dim_id = str(dim["id"])
        if dim_id in seen:
            raise ConfigError(f"评分卡档位 {profile!r} 维度 id 重复：{dim_id}")
        seen.add(dim_id)
        try:
            total_weight += float(dim["weight"])
        except (KeyError, TypeError, ValueError):
            raise ConfigError(f"评分卡维度 {dim_id} 的 weight 必须是数字") from None
        if not isinstance(dim.get("rules"), dict) or not dim["rules"]:
            raise ConfigError(f"评分卡维度 {dim_id} 缺少 rules")
    if abs(total_weight - 1.0) > 1e-9:
        raise ConfigError(f"评分卡档位 {profile!r} 维度权重合计应为 1.0，当前为 {total_weight}")
    grades = card.get("grades")
    if not isinstance(grades, list) or not grades:
        raise ConfigError(f"评分卡档位 {profile!r} 缺少 grades")
    for item in grades:
        if not isinstance(item, dict) or "grade" not in item or "minScore" not in item:
            raise ConfigError(f"评分卡档位 {profile!r} 的 grades 元素必须含 grade/minScore")
    confidence = card.get("confidence")
    if not isinstance(confidence, dict):
        raise ConfigError(f"评分卡档位 {profile!r} 缺少 confidence 配置")
    completeness = card.get("completeness")
    if not isinstance(completeness, dict) or not isinstance(completeness.get("sections"), list):
        raise ConfigError(f"评分卡档位 {profile!r} 缺少 completeness.sections")


def load_diagnosis_rules() -> dict[str, Any]:
    """加载诊断规则库（返回深拷贝，可安全修改）。"""
    data = _load_json_copy(DIAGNOSIS_RULES_PATH)
    if not isinstance(data, dict):
        raise ConfigError(f"诊断规则库 {DIAGNOSIS_RULES_PATH} 必须是 JSON 对象")
    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ConfigError(f"诊断规则库 {DIAGNOSIS_RULES_PATH} 缺少 rules")
    seen: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict) or not rule.get("ruleId") or not rule.get("name"):
            raise ConfigError("诊断规则必须包含 ruleId 与 name")
        rule_id = str(rule["ruleId"])
        if rule_id in seen:
            raise ConfigError(f"诊断规则 ruleId 重复：{rule_id}")
        seen.add(rule_id)
        try:
            score = float(rule["score"])
        except (KeyError, TypeError, ValueError):
            raise ConfigError(f"诊断规则 {rule_id} 的 score 必须是 0-1 的数字") from None
        if not 0.0 <= score <= 1.0:
            raise ConfigError(f"诊断规则 {rule_id} 的 score 必须在 0-1 之间")
        conditions = rule.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            raise ConfigError(f"诊断规则 {rule_id} 缺少 conditions")
    return data


# ---------------------------------------------------------------------------
# 确定性数值 / 日期工具
# ---------------------------------------------------------------------------
def parse_date(value: Any) -> date | None:
    """解析 ``yyyy-MM-dd`` 或 ISO 日期时间字符串，失败返回 None（不抛异常）。"""
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text[:10]
    try:
        return date.fromisoformat(candidate)
    except ValueError:
        return None


def round_half_up(value: float | int, digits: int = 2) -> float:
    """四舍五入（half-up），避免二进制浮点与银行家舍入带来的不确定尾数。"""
    quant = Decimal(1).scaleb(-int(digits))
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def format_number(value: Any, digits: int = 2) -> str:
    """把数字格式化为稳定的短文本（如 70、75.8、99.98）。"""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int):
        return str(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    rounded = round_half_up(number, digits)
    text = f"{rounded:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"
