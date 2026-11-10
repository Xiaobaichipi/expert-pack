#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""变电分析引擎核心包（substation-analysis-mcp）。

模块划分
--------
- ``config``     评分卡 / 诊断规则库加载与确定性工具函数；
- ``evidence``   证据链结构、数据段存在性与取数辅助；
- ``health``     健康度评分卡（单设备 + 站级）；
- ``diagnosis``  跨域证据链诊断（规则库驱动）；
- ``patterns``   重复缺陷 / 家族性缺陷聚类；
- ``metrics``    派生指标计算；
- ``report``     3 类 Markdown 报告模板渲染。

约束：纯 Python 3.10+ 标准库，无网络、无凭证；除报告 ``generatedAt`` 外不读系统时钟。
"""

from __future__ import annotations

__version__ = "1.1.0"
__all__ = [
    "__version__",
    "SKILL_NAME",
    "DEFAULT_PROFILE",
    "assess_device_health",
    "assess_station_health",
    "compute_device_metrics",
    "diagnose_equipment",
    "detect_defect_patterns",
    "generate_report",
    "list_report_types",
]

SKILL_NAME = "substation-analysis-mcp"
DEFAULT_PROFILE = "default"

from .config import AnalysisError, BundleError, ConfigError, ReportError  # noqa: E402
from .diagnosis import diagnose_equipment  # noqa: E402
from .health import assess_device_health, assess_station_health  # noqa: E402
from .metrics import compute_device_metrics  # noqa: E402
from .patterns import detect_defect_patterns  # noqa: E402
from .report import generate_report, list_report_types  # noqa: E402
