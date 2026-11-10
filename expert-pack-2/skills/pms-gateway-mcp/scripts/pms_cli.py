#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pms-gateway-mcp 命令行工具（26 个 PMS 接口的本地/联调入口）。

子命令::

    list-tools                    列出全部工具（26 个）与分组
    describe <tool>               查看单个工具的入参、返回、典型问数、示例参数
    call <tool> --params '<json>' 调用工具（默认 mock 模式直接出样例数据）
    serve                         以 stdio 方式启动 MCP Server（宿主挂载用）
    doctor                        环境/配置/规格/mock 数据自检
    mock-server                   启动本地可鉴权模拟网关（token/appkey/none，阻塞运行）

所有输出为 UTF-8 JSON（``ensure_ascii=False``）；错误写到 stderr 并以非 0 退出。

示例::

    python pms_cli.py doctor
    python pms_cli.py call get_asset_by_id --params '{"assetId":"AST-102-0001"}'
    python pms_cli.py call inquire_defect --params '{"defectLevel":"严重","pageSize":5}'
    python pms_cli.py mock-server --host 127.0.0.1 --port 18080 --auth-mode token
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

from pms_client import (  # noqa: E402  (需先插入 sys.path)
    PmsClient,
    PmsConfig,
    PmsError,
    __version__,
)

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_USAGE_ERROR = 2


class UsageError(Exception):
    """命令行用法错误（退出码 2）。"""


# ---------------------------------------------------------------------------
# 输出与配置
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
    """向 stdout 输出 JSON（ensure_ascii=False）。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None)
    stream = sys.stdout
    stream.write(text + "\n")
    stream.flush()


def emit_error(payload: Any, pretty: bool = True) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None)
    stream = sys.stderr
    stream.write(text + "\n")
    stream.flush()


def build_config(args: argparse.Namespace) -> PmsConfig:
    """CLI 显式参数优先，其余读环境变量。"""
    return PmsConfig.from_env(
        base_url=getattr(args, "base_url", None),
        auth_mode=getattr(args, "auth_mode", None),
        timeout=getattr(args, "timeout", None),
        retry=getattr(args, "retry", None),
        spec_path=getattr(args, "spec", None),
    )


def build_client(args: argparse.Namespace) -> PmsClient:
    return PmsClient(build_config(args))


def _parse_params(args: argparse.Namespace) -> dict[str, Any]:
    """解析 --params / --params-file。"""
    raw = getattr(args, "params", None)
    params_file = getattr(args, "params_file", None)
    if raw and params_file:
        raise UsageError("--params 与 --params-file 只能二选一")
    if params_file:
        path = Path(params_file)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise UsageError(f"无法读取参数文件 {path}：{exc}") from None
    if raw is None or str(raw).strip() == "":
        return {}
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise UsageError(
            f"--params 不是合法 JSON：{exc}。示例：--params '{{\"assetId\":\"AST-102-0001\"}}'"
        ) from None
    if not isinstance(value, dict):
        raise UsageError("--params 必须是 JSON 对象（key-value），例如 '{\"assetId\":\"AST-102-0001\"}'")
    return value


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------
def cmd_list_tools(args: argparse.Namespace) -> int:
    client = build_client(args)
    tools = client.list_tools()
    group_filter = getattr(args, "group", None)
    if group_filter:
        tools = [tool for tool in tools if tool["group"] == group_filter]
        if not tools:
            raise UsageError(
                f"分组 {group_filter!r} 下没有工具。可用分组："
                + "、".join(item["id"] for item in client.spec.group_summary())
            )
    emit(
        {
            "count": len(tools),
            "totalTools": len(client.spec.tools),
            "specVersion": client.spec.spec_version,
            "authMode": client.auth_mode,
            "groups": client.spec.group_summary(),
            "tools": tools,
        },
        pretty=not getattr(args, "compact", False),
    )
    return EXIT_OK


def cmd_describe(args: argparse.Namespace) -> int:
    client = build_client(args)
    detail = client.describe_tool(args.tool)
    detail["cliExample"] = {
        "command": f'call {args.tool}',
        "params": detail["exampleParams"],
    }
    detail["authMode"] = client.auth_mode
    emit(detail, pretty=not getattr(args, "compact", False))
    return EXIT_OK


def cmd_call(args: argparse.Namespace) -> int:
    client = build_client(args)
    params = _parse_params(args)
    envelope = client.call_tool(args.tool, params)
    payload: dict[str, Any] = dict(envelope)
    if getattr(args, "with_items", False):
        from pms_client import extract_list, extract_total

        items = extract_list(envelope)
        payload["items"] = items
        payload["total"] = extract_total(envelope) if extract_total(envelope) is not None else len(items)
    emit(payload, pretty=not getattr(args, "compact", False))
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    import mcp_server

    config = build_config(args)
    client = PmsClient(config)
    server = mcp_server.McpServer(client)
    return mcp_server.serve_stdio(server)


def cmd_doctor(args: argparse.Namespace) -> int:
    client = build_client(args)
    report = client.doctor_report(probe=not getattr(args, "no_probe", False))
    emit(report, pretty=not getattr(args, "compact", False))
    return EXIT_OK if report.get("ok") else EXIT_RUNTIME_ERROR


def cmd_mock_server(args: argparse.Namespace) -> int:
    """启动本地可鉴权模拟网关（阻塞运行，Ctrl+C 退出）。"""
    from mock_gateway.server import resolve_host_port, start_server

    host, port = resolve_host_port(getattr(args, "host", None), getattr(args, "port", None))
    auth_mode = getattr(args, "auth_mode", None) or "token"
    server = start_server(
        host,
        port,
        auth_mode,
        spec_path=getattr(args, "spec", None),
        verbose=bool(getattr(args, "verbose", False)),
    )
    token = server.auth.token
    app_key = server.auth.app_key
    app_secret = server.auth.app_secret
    _log_line("listening on {}（auth-mode={}，routes={}，Ctrl+C 退出）".format(server.base_url, server.auth.mode, len(server.routes)))
    _log_line("客户端对接方式（另开终端）：")
    _log_line('  $env:PMS_GATEWAY_BASE_URL = "{}"'.format(server.base_url))
    _log_line('  $env:PMS_AUTH_MODE = "{}"'.format(server.auth.mode))
    if server.auth.mode == "token":
        _log_line('  $env:PMS_TOKEN = "{}"   # 服务端期望 PMS_MOCK_TOKEN'.format(token))
    elif server.auth.mode == "appkey":
        _log_line('  $env:PMS_APP_KEY = "{}"'.format(app_key))
        _log_line('  $env:PMS_APP_SECRET = "{}"'.format(app_secret))
    else:
        _log_line("  # none 模式：免鉴权，仅供本地调试")
    _log_line("  python pms_cli.py doctor")
    try:
        server.wait()
    except KeyboardInterrupt:  # pragma: no cover - 交互式中断
        _log_line("收到 Ctrl+C，正在关闭模拟网关…")
    finally:
        server.stop()
    return EXIT_OK


def _log_line(message: str) -> None:
    """诊断信息一律写 stderr（stdout 只留给 JSON 结果）。"""
    sys.stderr.write("[pms-mock-gateway] {}\n".format(message))
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    # 用 SUPPRESS 默认值，避免子命令覆盖主命令上已解析的值
    common.add_argument("--spec", default=argparse.SUPPRESS, help="interfaces.json 路径")
    common.add_argument(
        "--auth-mode",
        default=argparse.SUPPRESS,
        choices=["mock", "none", "appkey", "token"],
        help="鉴权模式（默认读 PMS_AUTH_MODE，缺省 mock）",
    )
    common.add_argument("--base-url", default=argparse.SUPPRESS, help="网关地址（默认读 PMS_GATEWAY_BASE_URL）")
    common.add_argument("--timeout", type=float, default=argparse.SUPPRESS, help="请求超时秒数（默认读 PMS_TIMEOUT）")
    common.add_argument("--retry", type=int, default=argparse.SUPPRESS, help="重试次数（默认读 PMS_RETRY）")
    common.add_argument("--compact", action="store_true", default=argparse.SUPPRESS, help="输出单行 JSON")

    parser = argparse.ArgumentParser(
        prog="pms_cli.py",
        description="变电智能问数 · PMS 接口网关命令行（26 个接口，默认 mock 模式）",
        epilog="示例：pms_cli.py doctor / pms_cli.py list-tools / pms_cli.py call get_asset_by_id --params '{\"assetId\":\"AST-102-0001\"}'",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"pms-gateway-mcp {__version__}")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    p_list = subparsers.add_parser("list-tools", parents=[common], help="列出全部工具与分组")
    p_list.add_argument("--group", default=None, help="只看某个分组（如 asset-ledger）")
    p_list.set_defaults(func=cmd_list_tools)

    p_describe = subparsers.add_parser("describe", parents=[common], help="查看单个工具的详细定义")
    p_describe.add_argument("tool", help="工具名，如 get_asset_by_id")
    p_describe.set_defaults(func=cmd_describe)

    p_call = subparsers.add_parser("call", parents=[common], help="调用工具")
    p_call.add_argument("tool", help="工具名，如 get_asset_by_id")
    p_call.add_argument("--params", default=None, help="JSON 对象形式的参数，如 '{\"assetId\":\"AST-102-0001\"}'")
    p_call.add_argument("--params-file", default=None, help="从文件读取 JSON 参数（UTF-8）")
    p_call.add_argument("--with-items", action="store_true", help="额外输出兼容提取后的 items/total")
    p_call.set_defaults(func=cmd_call)

    p_serve = subparsers.add_parser("serve", parents=[common], help="启动 MCP stdio 服务（宿主挂载）")
    p_serve.set_defaults(func=cmd_serve)

    p_doctor = subparsers.add_parser("doctor", parents=[common], help="环境与配置自检")
    p_doctor.add_argument("--no-probe", action="store_true", help="跳过 mock 全量工具自检")
    p_doctor.set_defaults(func=cmd_doctor)

    p_mock = subparsers.add_parser(
        "mock-server",
        help="启动本地可鉴权模拟网关（token/appkey/none，阻塞运行）",
        description=(
            "启动本地可鉴权模拟网关：按 spec/interfaces.json 注册 26 条路由，"
            "支持 token / appkey / none 三种鉴权，供 pms_client 走真实 HTTP 链路联调。"
            "Ctrl+C 退出。"
        ),
    )
    p_mock.add_argument("--host", default=None, help="监听地址（默认读 PMS_MOCK_HOST，缺省 127.0.0.1）")
    p_mock.add_argument(
        "--port",
        type=int,
        default=None,
        help="监听端口（默认读 PMS_MOCK_PORT，缺省 18080；传 0 由系统分配空闲端口）",
    )
    p_mock.add_argument(
        "--auth-mode",
        default="token",
        choices=["token", "appkey", "none"],
        help="鉴权模式：token（Bearer）/appkey（HMAC 签名）/none（免鉴权，仅本地调试）",
    )
    p_mock.add_argument("--spec", default=None, help="interfaces.json 路径（默认自动定位）")
    p_mock.add_argument("--verbose", action="store_true", help="把每个请求打到 stderr（排障用）")
    p_mock.set_defaults(func=cmd_mock_server)

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
    except PmsError as exc:
        emit_error({"ok": False, "error": exc.to_dict()})
        return EXIT_RUNTIME_ERROR
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    except Exception as exc:  # pragma: no cover - 兜底
        emit_error({"ok": False, "error": {"code": "INTERNAL", "message": f"{type(exc).__name__}: {exc}"}})
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main())
