#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""substation-analysis-mcp 命令行工具（本地/联调/演示入口）。

子命令::

    health              单设备健康度评分（assess_device_health）
    station-health      站级健康画像（assess_station_health）
    diagnose            跨域证据链诊断（diagnose_equipment）
    patterns            重复/家族缺陷识别（detect_defect_patterns）
    metrics             派生指标计算（compute_device_metrics）
    report              报告渲染（generate_report）
    list-report-types   列出报告模板及所需 payload 键
    demo                一条命令跑通 健康+诊断+模式+指标+报告 并打印摘要

通用参数：``--bundle <file|->``、``--as-of yyyy-MM-dd``、``--compact``。
所有输出为 UTF-8 JSON（``ensure_ascii=False``）；错误写 stderr，退出码：0 成功 / 1 运行错误 / 2 用法错误。

示例::

    python analysis_cli.py demo
    python analysis_cli.py health --bundle assets/demo_bundle.json
    python analysis_cli.py report --type device_profile --bundle assets/demo_bundle.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from analysis import (  # noqa: E402  (需先插入 sys.path)
    AnalysisError,
    BundleError,
    __version__,
    assess_device_health,
    assess_station_health,
    compute_device_metrics,
    detect_defect_patterns,
    diagnose_equipment,
    generate_report,
    list_report_types,
)
from analysis.config import ASSETS_DIR, parse_date, read_json_file  # noqa: E402

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_USAGE_ERROR = 2

DEMO_BUNDLE_PATH = ASSETS_DIR / "demo_bundle.json"


class UsageError(Exception):
    """命令行用法错误（退出码 2）。"""


class DataLoadError(Exception):
    """输入文件读取/解析失败（退出码 1）。"""


# ---------------------------------------------------------------------------
# 输出与输入
# ---------------------------------------------------------------------------
def _configure_stdio() -> None:
    """统一 stdout/stderr 为 UTF-8，避免 Windows 控制台中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # pragma: no cover
                pass


def emit(payload: Any, pretty: bool = True) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def emit_error(payload: Any, pretty: bool = True) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None)
    sys.stderr.write(text + "\n")
    sys.stderr.flush()


def _read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    file_path = Path(path)
    try:
        return file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DataLoadError(f"无法读取文件 {file_path}：{exc}") from None


def load_json(path: str, what: str = "文件") -> Any:
    text = _read_text(path)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise DataLoadError(f"{what} {path} 不是合法 JSON：{exc}") from None


def load_bundle(path: str) -> dict[str, Any]:
    data = load_json(path, "bundle")
    if not isinstance(data, dict) or not isinstance(data.get("device"), dict):
        raise DataLoadError(f"bundle 文件 {path} 必须是包含 device 对象的 JSON")
    return data


def resolve_as_of(args: argparse.Namespace) -> str | None:
    value = getattr(args, "as_of", None)
    if value is None:
        return None
    if parse_date(value) is None:
        raise UsageError(f"--as-of 日期无法解析：{value!r}，应为 yyyy-MM-dd")
    return value


def _bundle_as_of(bundle: dict[str, Any], args: argparse.Namespace) -> str | None:
    explicit = resolve_as_of(args)
    if explicit:
        return explicit
    time_window = bundle.get("timeWindow")
    if isinstance(time_window, dict) and time_window.get("end"):
        return str(time_window.get("end"))
    return None


def require_bundle_arg(args: argparse.Namespace) -> str:
    value = getattr(args, "bundle", None)
    if not value:
        raise UsageError(f"{getattr(args, 'command', '该命令')} 需要 --bundle <文件路径>")
    return str(value)


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
def cmd_health(args: argparse.Namespace) -> int:
    bundle = load_bundle(require_bundle_arg(args))
    result = assess_device_health(
        bundle, getattr(args, "profile", "default"), as_of=resolve_as_of(args)
    )
    emit(result, pretty=not args.compact)
    return EXIT_OK


def cmd_station_health(args: argparse.Namespace) -> int:
    data = load_json(require_bundle_arg(args), "bundle")
    station_meta: dict[str, Any] = {}
    if isinstance(data, list):
        bundles = data
    elif isinstance(data, dict) and isinstance(data.get("bundles"), list):
        bundles = data["bundles"]
        if isinstance(data.get("station"), dict):
            station_meta = data["station"]
    elif isinstance(data, dict) and isinstance(data.get("device"), dict):
        bundles = [data]
    else:
        raise UsageError(
            "station-health 需要 bundle 数组、{\"bundles\": [...]} 或单个含 device 的数据包"
        )
    if getattr(args, "station_meta", None):
        try:
            extra_meta = json.loads(args.station_meta)
        except ValueError as exc:
            raise UsageError(f"--station-meta 不是合法 JSON：{exc}") from None
        if not isinstance(extra_meta, dict):
            raise UsageError("--station-meta 必须是 JSON 对象")
        station_meta = {**station_meta, **extra_meta}
    result = assess_station_health(
        bundles,
        station_meta or None,
        getattr(args, "profile", "default"),
        getattr(args, "top_n", 5),
        as_of=resolve_as_of(args),
    )
    emit(result, pretty=not args.compact)
    return EXIT_OK


def cmd_diagnose(args: argparse.Namespace) -> int:
    bundle = load_bundle(require_bundle_arg(args))
    result = diagnose_equipment(
        bundle, getattr(args, "max_hypotheses", 5), as_of=resolve_as_of(args)
    )
    emit(result, pretty=not args.compact)
    return EXIT_OK


def cmd_patterns(args: argparse.Namespace) -> int:
    bundle = load_bundle(require_bundle_arg(args))
    defects = bundle.get("defects")
    if not isinstance(defects, list):
        raise DataLoadError("bundle 缺少 defects 数组，无法做缺陷模式识别")
    result = detect_defect_patterns(
        defects,
        device_meta=bundle.get("device") if isinstance(bundle.get("device"), dict) else None,
        window_days=getattr(args, "window_days", 365),
        family_min_count=getattr(args, "family_min_count", 3),
        as_of=_bundle_as_of(bundle, args),
    )
    emit(result, pretty=not args.compact)
    return EXIT_OK


def cmd_metrics(args: argparse.Namespace) -> int:
    bundle = load_bundle(require_bundle_arg(args))
    result = compute_device_metrics(bundle, as_of=resolve_as_of(args))
    emit(result, pretty=not args.compact)
    return EXIT_OK


def cmd_list_report_types(args: argparse.Namespace) -> int:
    emit(list_report_types(), pretty=not args.compact)
    return EXIT_OK


def _combine_gaps(*values: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for value in values:
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                key = (item.get("section"), item.get("field"), item.get("reason"))
            else:
                key = ("report", None, str(item))
                item = {"section": "report", "field": None, "reason": str(item)}
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
    return result


def build_device_payload(bundle: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    health = assess_device_health(bundle, as_of=resolve_as_of(args))
    diagnosis = diagnose_equipment(bundle, as_of=resolve_as_of(args))
    metrics = compute_device_metrics(bundle, as_of=resolve_as_of(args))
    patterns = detect_defect_patterns(
        bundle.get("defects") if isinstance(bundle.get("defects"), list) else [],
        device_meta=bundle.get("device"),
        as_of=_bundle_as_of(bundle, args),
    )
    return {
        "device": bundle.get("device"),
        "health": health,
        "diagnosis": diagnosis,
        "metrics": metrics,
        "patterns": patterns,
        "defects": bundle.get("defects", []),
        "tests": bundle.get("tests", []),
        "faults": bundle.get("faults", []),
        "timeWindow": bundle.get("timeWindow"),
        "asOf": health.get("asOf"),
        "dataGaps": _combine_gaps(
            health.get("dataGaps"),
            diagnosis.get("dataGaps"),
            metrics.get("dataGaps"),
            patterns.get("dataGaps"),
        ),
    }


def build_station_payload(data: Any, args: argparse.Namespace) -> dict[str, Any]:
    if isinstance(data, list):
        bundles = data
        station_meta: dict[str, Any] = {}
    elif isinstance(data, dict) and isinstance(data.get("bundles"), list):
        bundles = data["bundles"]
        station_meta = data.get("station") if isinstance(data.get("station"), dict) else {}
    elif isinstance(data, dict) and isinstance(data.get("device"), dict):
        bundles = [data]
        station_meta = {}
    else:
        raise UsageError("station_monthly 报告需要 bundle 数组或 {\"bundles\": [...]} 文件")
    station_result = assess_station_health(
        bundles,
        station_meta,
        getattr(args, "profile", "default"),
        getattr(args, "top_n", 5),
        as_of=resolve_as_of(args),
    )
    period = None
    first = bundles[0] if bundles and isinstance(bundles[0], dict) else {}
    time_window = first.get("timeWindow") if isinstance(first.get("timeWindow"), dict) else {}
    if time_window.get("start") or time_window.get("end"):
        period = f"{time_window.get('start') or '未标注'} 至 {time_window.get('end') or '未标注'}"
    if period:
        station_result["period"] = period
    station_result.setdefault("dataGaps", [])
    return station_result


def build_fault_payload(bundle: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    faults = bundle.get("faults") if isinstance(bundle.get("faults"), list) else []
    fault = faults[0] if faults and isinstance(faults[0], dict) else {}
    diagnosis = diagnose_equipment(bundle, as_of=resolve_as_of(args))
    health = assess_device_health(bundle, as_of=resolve_as_of(args))
    metrics = compute_device_metrics(bundle, as_of=resolve_as_of(args))
    return {
        "device": bundle.get("device"),
        "fault": fault,
        "defects": bundle.get("defects", []),
        "tests": bundle.get("tests", []),
        "faults": faults,
        "health": health,
        "diagnosis": diagnosis,
        "metrics": metrics,
        "timeWindow": bundle.get("timeWindow"),
        "asOf": health.get("asOf"),
        "dataGaps": _combine_gaps(
            health.get("dataGaps"), diagnosis.get("dataGaps"), metrics.get("dataGaps")
        ),
    }


def build_report_payload(report_type: str, data: Any, args: argparse.Namespace) -> dict[str, Any]:
    if report_type == "device_profile":
        if not isinstance(data, dict):
            raise UsageError("device_profile 报告需要单个设备 bundle")
        return build_device_payload(data, args)
    if report_type == "station_monthly":
        return build_station_payload(data, args)
    if report_type == "fault_review":
        if not isinstance(data, dict):
            raise UsageError("fault_review 报告需要单个设备 bundle")
        return build_fault_payload(data, args)
    raise UsageError(f"未知报告类型：{report_type}")


def cmd_report(args: argparse.Namespace) -> int:
    citations = None
    if getattr(args, "citations", None):
        citations = load_json(args.citations, "citations")
        if not isinstance(citations, list):
            raise DataLoadError("citations 文件必须是 JSON 数组")
    if getattr(args, "payload", None):
        payload = load_json(args.payload, "payload")
        if not isinstance(payload, dict):
            raise DataLoadError("payload 文件必须是 JSON 对象")
    elif getattr(args, "bundle", None):
        payload = build_report_payload(args.type, load_json(args.bundle, "bundle"), args)
    else:
        raise UsageError("report 需要 --payload 或 --bundle 之一")
    result = generate_report(args.type, payload, citations=citations, title=getattr(args, "title", None))
    emit(result, pretty=not args.compact)
    return EXIT_OK


def cmd_demo(args: argparse.Namespace) -> int:
    bundle_path = getattr(args, "bundle", None) or str(DEMO_BUNDLE_PATH)
    bundle = load_bundle(bundle_path)
    as_of = _bundle_as_of(bundle, args)
    health = assess_device_health(bundle, as_of=as_of)
    diagnosis = diagnose_equipment(bundle, as_of=as_of)
    metrics = compute_device_metrics(bundle, as_of=as_of)
    patterns = detect_defect_patterns(
        bundle.get("defects") if isinstance(bundle.get("defects"), list) else [],
        device_meta=bundle.get("device"),
        as_of=as_of,
    )
    payload = build_device_payload(bundle, args)
    report = generate_report("device_profile", payload)
    summary = {
        "device": (bundle.get("device") or {}).get("name"),
        "score": health["score"],
        "grade": health["grade"],
        "gradeLabel": health["gradeLabel"],
        "risk": health["risk"],
        "confidence": health["confidence"],
        "completeness": health["completeness"],
        "dimensions": [
            {"id": item["id"], "score": item["score"], "deduction": item["deduction"]}
            for item in health["dimensions"]
        ],
        "deductionCount": len(health["deductions"]),
        "topHypotheses": [
            {
                "ruleId": item["ruleId"],
                "name": item["name"],
                "score": item["score"],
                "confidence": item["confidence"],
            }
            for item in diagnosis["hypotheses"][:3]
        ],
        "patternSummary": patterns["summary"],
        "metrics": metrics["metrics"],
        "report": {
            "reportType": report["reportType"],
            "title": report["title"],
            "sectionCount": len(report["sections"]),
            "markdownChars": len(report["markdown"]),
            "dataGapCount": len(report["dataGaps"]),
        },
        "reportTypes": len(list_report_types()["reportTypes"]),
    }
    emit(
        {
            "demo": True,
            "bundlePath": bundle_path,
            "summary": summary,
            "health": health,
            "diagnosis": diagnosis,
            "patterns": patterns,
            "metrics": metrics,
            "report": report,
        },
        pretty=not args.compact,
    )
    return EXIT_OK


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--bundle", default=None, help="bundle JSON 文件路径（'-' 表示 stdin）")
    common.add_argument("--as-of", default=None, help="分析时间基准 yyyy-MM-dd（默认取 bundle.timeWindow.end）")
    common.add_argument("--profile", default="default", help="评分卡档位（默认 default）")
    common.add_argument("--compact", action="store_true", help="输出单行 JSON")

    parser = argparse.ArgumentParser(
        prog="analysis_cli.py",
        description="变电分析引擎命令行（健康度/诊断/模式/指标/报告，7 个工具）",
        epilog="示例：analysis_cli.py demo / analysis_cli.py health --bundle assets/demo_bundle.json",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"substation-analysis-mcp {__version__}")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    p_health = subparsers.add_parser("health", parents=[common], help="单设备健康度评分")
    p_health.set_defaults(func=cmd_health)

    p_station = subparsers.add_parser("station-health", parents=[common], help="站级健康画像")
    p_station.add_argument("--station-meta", default=None, help="站元数据 JSON 字符串")
    p_station.add_argument("--top-n", type=int, default=5, help="风险设备 TopN（默认 5）")
    p_station.set_defaults(func=cmd_station_health)

    p_diagnose = subparsers.add_parser("diagnose", parents=[common], help="跨域证据链诊断")
    p_diagnose.add_argument("--max-hypotheses", type=int, default=5, help="最多假设数（默认 5）")
    p_diagnose.set_defaults(func=cmd_diagnose)

    p_patterns = subparsers.add_parser("patterns", parents=[common], help="重复/家族缺陷识别")
    p_patterns.add_argument("--window-days", type=int, default=365, help="聚类窗口天数（默认 365）")
    p_patterns.add_argument("--family-min-count", type=int, default=3, help="家族性缺陷最小设备数（默认 3）")
    p_patterns.set_defaults(func=cmd_patterns)

    p_metrics = subparsers.add_parser("metrics", parents=[common], help="派生指标计算")
    p_metrics.set_defaults(func=cmd_metrics)

    p_report = subparsers.add_parser("report", parents=[common], help="报告渲染")
    p_report.add_argument(
        "--type",
        required=True,
        choices=["device_profile", "station_monthly", "fault_review"],
        help="报告模板类型",
    )
    p_report.add_argument("--payload", default=None, help="分析结果负载 JSON 文件（与 --bundle 二选一）")
    p_report.add_argument("--citations", default=None, help="知识库引用 JSON 数组文件")
    p_report.add_argument("--title", default=None, help="自定义报告标题")
    p_report.set_defaults(func=cmd_report)

    p_types = subparsers.add_parser("list-report-types", parents=[common], help="列出报告模板及所需字段")
    p_types.set_defaults(func=cmd_list_report_types)

    p_demo = subparsers.add_parser("demo", parents=[common], help="一条命令跑通全部分析能力")
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help(sys.stderr)
        return EXIT_USAGE_ERROR
    try:
        return int(args.func(args))
    except UsageError as exc:
        emit_error({"ok": False, "error": {"code": "USAGE_ERROR", "message": str(exc)}})
        return EXIT_USAGE_ERROR
    except BundleError as exc:
        emit_error({"ok": False, "error": exc.to_dict()})
        return EXIT_RUNTIME_ERROR
    except DataLoadError as exc:
        emit_error({"ok": False, "error": {"code": "DATA_ERROR", "message": str(exc)}})
        return EXIT_RUNTIME_ERROR
    except AnalysisError as exc:
        emit_error({"ok": False, "error": exc.to_dict()})
        return EXIT_RUNTIME_ERROR
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    except Exception as exc:  # pragma: no cover - 兜底
        emit_error(
            {"ok": False, "error": {"code": "INTERNAL", "message": f"{type(exc).__name__}: {exc}"}}
        )
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main())

