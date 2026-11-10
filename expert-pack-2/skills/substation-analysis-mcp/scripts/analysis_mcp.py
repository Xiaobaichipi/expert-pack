#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""substation-analysis-mcp —— 变电分析引擎 MCP Server（stdio / 换行分隔 JSON-RPC 2.0）。

协议约定
--------
- 传输：stdin/stdout 双向，**一行一条 JSON-RPC 2.0 消息**（UTF-8，``\\n`` 分隔）；
- stdout **只输出协议消息**，日志/诊断/异常栈一律写 stderr；
- 支持方法：``initialize`` / ``notifications/initialized`` / ``ping`` / ``tools/list`` / ``tools/call``；
- 工具清单与参数以 ``spec/analysis-tools.json`` 为唯一事实源（7 个工具），
  ``tools/list`` 每次调用都会按本文件中的 ``TOOL_DEFS`` 生成，与 spec 逐字段一致；
- 错误码：解析失败 -32700；非法请求 -32600；未知方法 -32601；参数错误 -32602；
  服务端内部错误 -32603。业务数据错误（如 bundle 不合法）通过 ``tools/call`` 的
  ``isError=true`` 信封返回，便于模型纠正输入。

启动（宿主以 stdio 方式拉起，无需参数）::

    python expert-pack/skills/substation-analysis-mcp/scripts/analysis_mcp.py
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Iterable, TextIO

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from analysis import (  # noqa: E402  (需先插入 sys.path)
    AnalysisError,
    __version__,
    assess_device_health,
    assess_station_health,
    compute_device_metrics,
    detect_defect_patterns,
    diagnose_equipment,
    generate_report,
    list_report_types,
)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "substation-analysis-mcp"
SERVER_VERSION = __version__

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

#: 通知类方法（无响应）
NOTIFICATION_METHODS = (
    "notifications/initialized",
    "notifications/cancelled",
    "notifications/roots/list_changed",
)

#: 7 个分析工具契约（name / 参数 / required / enum / default 与 spec/analysis-tools.json 一致）
TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "assess_device_health",
        "description": "对单台设备按评分卡计算健康度分数、等级、各维度得分与扣分证据，并给出数据完备度与置信度。",
        "params": [
            {
                "name": "bundle",
                "type": "object",
                "required": True,
                "description": "设备数据包，字段见 analysis-bundle.schema.json",
            },
            {
                "name": "scorecard_profile",
                "type": "string",
                "required": False,
                "default": "default",
                "description": "评分卡档位，默认 default",
            },
        ],
    },
    {
        "name": "assess_station_health",
        "description": "对同一变电站多台设备批量评分，输出站级均值、等级分布、风险设备 TopN 与站级风险结论。",
        "params": [
            {
                "name": "bundles",
                "type": "array",
                "required": True,
                "description": "设备数据包数组（同一站）",
            },
            {
                "name": "station_meta",
                "type": "object",
                "required": False,
                "description": "站元数据：stationId/stationName/voltageLevel",
            },
            {
                "name": "scorecard_profile",
                "type": "string",
                "required": False,
                "default": "default",
                "description": "评分卡档位，默认 default",
            },
            {
                "name": "top_n",
                "type": "integer",
                "required": False,
                "default": 5,
                "description": "风险设备 TopN 数量",
            },
        ],
    },
    {
        "name": "diagnose_equipment",
        "description": "基于缺陷/故障/试验/修试/负载等跨域证据，按规则库给出根因假设排序、证据链、缺失证据与下一步核查建议。",
        "params": [
            {
                "name": "bundle",
                "type": "object",
                "required": True,
                "description": "设备数据包",
            },
            {
                "name": "max_hypotheses",
                "type": "integer",
                "required": False,
                "default": 5,
                "description": "最多返回的根因假设数量",
            },
        ],
    },
    {
        "name": "detect_defect_patterns",
        "description": "对缺陷记录做聚类：同部位重复缺陷、同型号同厂家家族性缺陷、同批次/同期投运设备共性问题。",
        "params": [
            {
                "name": "defects",
                "type": "array",
                "required": True,
                "description": "缺陷记录数组（至少含 level/status/discoverTime/part）",
            },
            {
                "name": "device_meta",
                "type": "object",
                "required": False,
                "description": "设备元数据：model/manufacturer/commissioningDate/deviceType",
            },
            {
                "name": "window_days",
                "type": "integer",
                "required": False,
                "default": 365,
                "description": "聚类时间窗口（天）",
            },
            {
                "name": "family_min_count",
                "type": "integer",
                "required": False,
                "default": 3,
                "description": "家族性缺陷最小设备数",
            },
        ],
    },
    {
        "name": "compute_device_metrics",
        "description": "由设备数据包计算派生指标：缺陷率、危急未闭环、超期未消缺、检修计划完成率、修试完成率、负载率、可开放容量比、可用率等。",
        "params": [
            {
                "name": "bundle",
                "type": "object",
                "required": True,
                "description": "设备数据包",
            }
        ],
    },
    {
        "name": "generate_report",
        "description": "把分析结果按模板渲染为 Markdown 报告；支持设备画像、站级月报、故障复盘三类模板，可附加知识库引用。",
        "params": [
            {
                "name": "report_type",
                "type": "string",
                "required": True,
                "enum": ["device_profile", "station_monthly", "fault_review"],
                "description": "报告模板类型",
            },
            {
                "name": "payload",
                "type": "object",
                "required": True,
                "description": "分析结果负载（健康度/诊断/指标/清单等）",
            },
            {
                "name": "citations",
                "type": "array",
                "required": False,
                "description": "知识库引用：[{title, source, snippet, kbId}]",
            },
            {
                "name": "title",
                "type": "string",
                "required": False,
                "description": "自定义标题",
            },
        ],
    },
    {
        "name": "list_report_types",
        "description": "列出可用报告模板及所需字段，供编排层选择。",
        "params": [],
    },
]

_TYPE_NAMES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def log(message: str) -> None:
    """诊断日志只写 stderr，绝不污染 stdout 协议通道。"""
    stream = _LOG_STREAM if _LOG_STREAM is not None else sys.stderr
    try:
        print(f"[{SERVER_NAME}] {message}", file=stream, flush=True)
    except Exception:  # pragma: no cover - stderr 不可用时静默
        pass


#: 运行期日志流（serve_stdio 可注入，便于测试与宿主重定向）
_LOG_STREAM: TextIO | None = None


class JsonRpcError(Exception):
    """处理消息时主动抛出的 JSON-RPC 错误。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _type_matches(value: Any, type_name: str) -> bool:
    expected = _TYPE_NAMES.get(type_name)
    if expected is None:
        return True
    if type_name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def tool_schemas() -> list[dict[str, Any]]:
    """生成 tools/list 返回的工具 schema（与 spec 对齐）。"""
    tools: list[dict[str, Any]] = []
    for tool in TOOL_DEFS:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in tool["params"]:
            prop: dict[str, Any] = {
                "type": param["type"],
                "description": param.get("description", ""),
            }
            if "default" in param:
                prop["default"] = param["default"]
            if "enum" in param:
                prop["enum"] = list(param["enum"])
            properties[param["name"]] = prop
            if param.get("required"):
                required.append(param["name"])
        tools.append(
            {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }
        )
    return tools


_TOOL_MAP = {tool["name"]: tool for tool in TOOL_DEFS}


def validate_arguments(tool_name: str, arguments: dict[str, Any]) -> None:
    """按工具契约校验参数：必填、类型、枚举；未知参数忽略（保持宿主兼容）。"""
    tool = _TOOL_MAP.get(tool_name)
    if tool is None:
        raise JsonRpcError(INVALID_PARAMS, f"未知工具：{tool_name}")
    params = {param["name"]: param for param in tool["params"]}
    for param in tool["params"]:
        if param.get("required") and param["name"] not in arguments:
            raise JsonRpcError(INVALID_PARAMS, f"缺少必需参数：{param['name']}")
    for name, value in arguments.items():
        spec = params.get(name)
        if spec is None:
            continue
        if not _type_matches(value, str(spec["type"])):
            raise JsonRpcError(
                INVALID_PARAMS, f"参数 {name} 类型错误：要求 {spec['type']}，实际 {type(value).__name__}"
            )
        enum_values = spec.get("enum")
        if enum_values and value not in enum_values:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"参数 {name} 取值不合法：{value!r}，可选 {'/'.join(str(item) for item in enum_values)}",
            )


def _call_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name == "assess_device_health":
        return assess_device_health(
            arguments["bundle"], arguments.get("scorecard_profile", "default")
        )
    if name == "assess_station_health":
        return assess_station_health(
            arguments["bundles"],
            arguments.get("station_meta"),
            arguments.get("scorecard_profile", "default"),
            arguments.get("top_n", 5),
        )
    if name == "diagnose_equipment":
        return diagnose_equipment(arguments["bundle"], arguments.get("max_hypotheses", 5))
    if name == "detect_defect_patterns":
        return detect_defect_patterns(
            arguments["defects"],
            device_meta=arguments.get("device_meta"),
            window_days=arguments.get("window_days", 365),
            family_min_count=arguments.get("family_min_count", 3),
        )
    if name == "compute_device_metrics":
        return compute_device_metrics(arguments["bundle"])
    if name == "generate_report":
        return generate_report(
            arguments["report_type"],
            arguments["payload"],
            citations=arguments.get("citations"),
            title=arguments.get("title"),
        )
    if name == "list_report_types":
        return list_report_types()
    raise JsonRpcError(INVALID_PARAMS, f"未知工具：{name}")


class AnalysisMcpServer:
    """MCP 协议处理器（与传输解耦，便于单元测试直接调用）。"""

    def __init__(
        self,
        *,
        server_name: str = SERVER_NAME,
        server_version: str = SERVER_VERSION,
    ) -> None:
        self.server_name = server_name
        self.server_version = server_version
        self.initialized = False
        self.tool_count = len(TOOL_DEFS)
        log(f"init: tools={self.tool_count} skillDir={_SCRIPTS_DIR.parent}")

    # ------------------------------------------------------------------
    # 消息入口
    # ------------------------------------------------------------------
    def handle_message(self, message: Any) -> dict[str, Any] | None:
        """处理一条已解析的 JSON-RPC 消息，返回响应对象（通知返回 None）。"""
        if isinstance(message, list):
            responses = [
                response
                for response in (self.handle_message(item) for item in message)
                if response is not None
            ]
            return responses or None
        if not isinstance(message, dict):
            return self._error_response(None, INVALID_REQUEST, "请求必须是 JSON 对象")
        if not isinstance(message.get("jsonrpc"), str):
            return self._error_response(
                message.get("id"), INVALID_REQUEST, "缺少 jsonrpc 字段，仅支持 JSON-RPC 2.0"
            )

        method = message.get("method")
        params = message.get("params")
        has_id = "id" in message
        msg_id = message.get("id")

        if not isinstance(method, str) or not method:
            return self._error_response(msg_id, INVALID_REQUEST, "缺少 method 字段")
        if params is not None and not isinstance(params, (dict, list)):
            if has_id:
                return self._error_response(msg_id, INVALID_PARAMS, "params 必须是对象或数组")
            return None

        if method in NOTIFICATION_METHODS or not has_id:
            try:
                self._dispatch(method, params)
            except JsonRpcError as exc:
                log(f"通知 {method} 处理失败：{exc.message}")
            except Exception as exc:  # pragma: no cover - 防御
                log(f"通知 {method} 异常：{type(exc).__name__}: {exc}")
            return None

        try:
            result = self._dispatch(method, params)
        except JsonRpcError as exc:
            return self._error_response(msg_id, exc.code, exc.message, exc.data)
        except Exception as exc:  # pragma: no cover - 防御未知异常
            log("内部异常：\n" + traceback.format_exc())
            return self._error_response(
                msg_id, INTERNAL_ERROR, f"服务端内部错误：{type(exc).__name__}: {exc}"
            )
        return self._result_response(msg_id, result)

    def handle_line(self, line: str) -> str | None:
        """处理一行文本（stdin 的一行），返回一行待输出文本（无响应返回 None）。"""
        if not isinstance(line, str):
            return None
        text = line.strip()
        if not text:
            return None
        try:
            message = json.loads(text)
        except ValueError as exc:
            log(f"JSON 解析失败：{exc}")
            return self._dump(self._error_response(None, PARSE_ERROR, f"JSON 解析失败：{exc}"))
        try:
            response = self.handle_message(message)
        except Exception as exc:  # pragma: no cover - handle_message 内部已兜底
            log("消息处理异常：\n" + traceback.format_exc())
            response = self._error_response(None, INTERNAL_ERROR, f"服务端内部错误：{exc}")
        if response is None:
            return None
        return self._dump(response)

    # ------------------------------------------------------------------
    # 方法分发
    # ------------------------------------------------------------------
    def _dispatch(self, method: str, params: Any) -> Any:
        if method == "initialize":
            return self._initialize(params)
        if method in NOTIFICATION_METHODS:
            if method == "notifications/initialized":
                self.initialized = True
                log("客户端已确认初始化完成（notifications/initialized）")
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": tool_schemas()}
        if method == "tools/call":
            return self._tools_call(params)
        if method == "resources/list":
            raise JsonRpcError(INVALID_PARAMS, "本服务未声明 resources 能力，请使用 tools/list")
        if method == "prompts/list":
            raise JsonRpcError(INVALID_PARAMS, "本服务未声明 prompts 能力，请使用 tools/list")
        raise JsonRpcError(METHOD_NOT_FOUND, f"不支持的方法：{method}")

    def _initialize(self, params: Any) -> dict[str, Any]:
        requested = ""
        if isinstance(params, dict):
            requested = str(params.get("protocolVersion") or "")
            client_info = params.get("clientInfo") or {}
            if isinstance(client_info, dict):
                log(
                    f"initialize: client={client_info.get('name')!r} "
                    f"version={client_info.get('version')!r} requestedProtocol={requested!r}"
                )
        else:
            log("initialize: params 非对象，按默认协议版本返回")
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": self.server_name, "version": self.server_version},
        }

    def _tools_call(self, params: Any) -> dict[str, Any]:
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise JsonRpcError(INVALID_PARAMS, "tools/call 的 params 必须是对象")
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise JsonRpcError(INVALID_PARAMS, "tools/call 缺少工具名 name")
        name = name.strip()
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(INVALID_PARAMS, "tools/call 的 arguments 必须是 JSON 对象")

        validate_arguments(name, arguments)
        try:
            result = _call_tool(name, arguments)
        except AnalysisError as exc:
            log(f"工具 {name} 执行失败：{exc.code} {exc.message}")
            return {
                "content": [{"type": "text", "text": self._dump({"error": exc.to_dict()})}],
                "isError": True,
            }
        except Exception as exc:  # pragma: no cover - 未知异常走协议级内部错误
            log(f"工具 {name} 内部异常：\n" + traceback.format_exc())
            raise JsonRpcError(
                INTERNAL_ERROR, f"工具 {name} 内部错误：{type(exc).__name__}: {exc}"
            ) from None
        return {
            "content": [{"type": "text", "text": self._dump(result)}],
            "isError": False,
        }

    # ------------------------------------------------------------------
    # 响应构造
    # ------------------------------------------------------------------
    @staticmethod
    def _dump(payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _result_response(msg_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _error_response(self, msg_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": msg_id, "error": error}


# ---------------------------------------------------------------------------
# stdio 服务循环
# ---------------------------------------------------------------------------
def _reconfigure(stream: TextIO | None, **kwargs: Any) -> None:
    if stream is None:
        return
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(**kwargs)
        except Exception:  # pragma: no cover - 非文本流/已关闭时忽略
            pass


def serve_stdio(
    server: AnalysisMcpServer | None = None,
    *,
    stdin: Iterable[str] | TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """stdio 主循环：逐行读请求、逐行写响应。"""
    server = server or AnalysisMcpServer()
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr

    if source is sys.stdin:
        _reconfigure(sys.stdin, encoding="utf-8", errors="replace")
    if sink is sys.stdout:
        _reconfigure(sys.stdout, encoding="utf-8", errors="replace")
    if err is sys.stderr:
        _reconfigure(sys.stderr, encoding="utf-8", errors="replace")

    global _LOG_STREAM
    previous_log_stream = _LOG_STREAM
    _LOG_STREAM = err
    log("stdio 服务已启动，等待 JSON-RPC 消息（Ctrl+C 退出）")
    try:
        for line in source:
            response = server.handle_line(line)
            if response is None:
                continue
            try:
                sink.write(response + "\n")
                sink.flush()
            except (BrokenPipeError, ValueError):  # 宿主提前关闭管道
                log("stdout 已关闭，退出服务")
                return 0
    except KeyboardInterrupt:  # pragma: no cover - 交互场景
        log("收到中断信号，退出服务")
    except (BrokenPipeError, ValueError):
        log("输入流已关闭，退出服务")
    finally:
        _LOG_STREAM = previous_log_stream
    log("stdio 服务已退出")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="analysis_mcp.py",
        description="变电分析引擎 MCP Server（stdio JSON-RPC 2.0，7 个分析工具）",
    )
    parser.add_argument("--server-name", default=SERVER_NAME, help=argparse.SUPPRESS)
    parser.add_argument("--server-version", default=SERVER_VERSION, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    server = AnalysisMcpServer(server_name=args.server_name, server_version=args.server_version)
    return serve_stdio(server)


if __name__ == "__main__":
    sys.exit(main())
