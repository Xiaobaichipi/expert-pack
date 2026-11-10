"""PMS 接口网关客户端。

统一入口 :meth:`PmsClient.call_tool` 负责：工具查表 → 参数校验/类型归一 → 按
``paramStyle`` 拆分 path/query/body → 走 mock 或真实网关 → 返回 ``{code, message, data}``。

同时为 26 个工具各提供一个**同名显式方法**（便于 IDE 补全、静态检查与宿主直接调用），
等价于带类型提示的 ``call_tool`` 快捷方式。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

from .auth import AuthProvider, create_auth_provider
from .config import PmsConfig
from .errors import ErrorCode, PmsError, internal_error, invalid_param
from .mock import MockBackend
from .spec import InterfaceSpec, ParamSpec, ToolSpec, load_spec
from .transport import Transport, extract_list, extract_total, filter_none

__all__ = [
    "PmsClient",
    "validate_arguments",
    "coerce_value",
    "extract_list",
    "extract_total",
]


# ---------------------------------------------------------------------------
# 参数校验与类型归一
# ---------------------------------------------------------------------------
def coerce_value(tool_name: str, param: ParamSpec, value: Any) -> Any:
    """按 spec 声明的类型做宽松但明确的类型转换，失败抛出 INVALID_PARAM。"""
    json_type = param.json_type
    if json_type == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        raise invalid_param(
            f"参数 {param.name} 应为字符串，实际收到 {type(value).__name__}",
            tool=tool_name,
            details={"param": param.name, "expected": "string"},
        )
    if json_type == "integer":
        if isinstance(value, bool):
            raise invalid_param(f"参数 {param.name} 应为整数，实际收到布尔值", tool=tool_name)
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                pass
        raise invalid_param(
            f"参数 {param.name} 应为整数，实际收到 {value!r}",
            tool=tool_name,
            details={"param": param.name, "expected": "integer"},
        )
    if json_type == "number":
        if isinstance(value, bool):
            raise invalid_param(f"参数 {param.name} 应为数字，实际收到布尔值", tool=tool_name)
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass
        raise invalid_param(
            f"参数 {param.name} 应为数字，实际收到 {value!r}",
            tool=tool_name,
            details={"param": param.name, "expected": "number"},
        )
    if json_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0"):
            return value.strip().lower() in ("true", "1")
        raise invalid_param(
            f"参数 {param.name} 应为布尔值（true/false），实际收到 {value!r}",
            tool=tool_name,
            details={"param": param.name, "expected": "boolean"},
        )
    if json_type == "array":
        if isinstance(value, (list, tuple)):
            return list(value)
        raise invalid_param(
            f"参数 {param.name} 应为数组，实际收到 {type(value).__name__}",
            tool=tool_name,
            details={"param": param.name, "expected": "array"},
        )
    if json_type == "object":
        if isinstance(value, Mapping):
            return dict(value)
        raise invalid_param(
            f"参数 {param.name} 应为对象，实际收到 {type(value).__name__}",
            tool=tool_name,
            details={"param": param.name, "expected": "object"},
        )
    return value


def validate_arguments(tool: ToolSpec, params: Any = None) -> dict[str, Any]:
    """校验并归一调用参数（未传的可选项不进入结果）。"""
    if params is None:
        params = {}
    if isinstance(params, str):
        text = params.strip()
        if not text:
            params = {}
        else:
            try:
                params = json.loads(text)
            except ValueError:
                raise invalid_param(
                    f"工具 {tool.name} 的参数不是合法 JSON：{params!r}",
                    tool=tool.name,
                ) from None
    if not isinstance(params, Mapping):
        raise invalid_param(
            f"工具 {tool.name} 的参数必须是 JSON 对象（key-value），实际收到 {type(params).__name__}",
            tool=tool.name,
        )

    allowed = [param.name for param in tool.params]
    unknown = sorted(str(key) for key in params if str(key) not in allowed)
    if unknown:
        raise invalid_param(
            f"工具 {tool.name} 不支持参数：{', '.join(unknown)}。可用参数：{', '.join(allowed) if allowed else '（无）'}",
            tool=tool.name,
            details={"unknown": unknown, "allowed": allowed},
        )

    args: dict[str, Any] = {}
    missing: list[str] = []
    for param in tool.params:
        raw = params.get(param.name)
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            if param.required:
                missing.append(param.name)
            continue
        args[param.name] = coerce_value(tool.name, param, raw)
    if missing:
        hint = "；".join(f"{param.name}（{param.desc}）" for param in tool.params if param.name in missing)
        raise invalid_param(
            f"工具 {tool.name} 缺少必填参数：{', '.join(missing)}。说明：{hint}",
            tool=tool.name,
            details={"missing": missing},
        )
    return args


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------
class PmsClient:
    """26 个 PMS 工具的调用客户端（mock / none / token / appkey 四种鉴权）。"""

    def __init__(
        self,
        config: PmsConfig | None = None,
        *,
        spec: InterfaceSpec | None = None,
        transport: Transport | None = None,
        auth: AuthProvider | None = None,
    ) -> None:
        self.config = config or PmsConfig.from_env()
        self.spec = spec or load_spec(self.config.spec_path)
        self.auth = auth or create_auth_provider(self.config)
        self.transport = transport or Transport(self.config, self.auth)
        self.mock_backend = MockBackend(self.spec)

    # -- 只读信息 -------------------------------------------------------
    @property
    def auth_mode(self) -> str:
        return self.config.auth_mode

    @property
    def is_mock(self) -> bool:
        return self.config.is_mock

    def list_tools(self) -> list[dict[str, Any]]:
        """工具目录（简化版，供 CLI list-tools）。"""
        return [
            {
                "name": tool.name,
                "title": tool.title,
                "code": tool.code,
                "group": tool.group,
                "groupTitle": tool.group_title,
                "groupSkill": tool.group_skill,
                "method": tool.method,
                "path": tool.path,
                "required": [param.name for param in tool.required_params],
                "paged": tool.is_paged,
            }
            for tool in self.spec.tools
        ]

    def tool_schemas(self) -> list[dict[str, Any]]:
        """MCP tools/list 结构。"""
        return self.spec.tool_schemas()

    def input_schema(self, name: str) -> dict[str, Any]:
        return self.spec.get(name).input_schema()

    def describe_tool(self, name: str) -> dict[str, Any]:
        return self.spec.get(name).describe()

    # -- 统一调用入口 ---------------------------------------------------
    def call_tool(self, name: str, params: Any = None) -> dict[str, Any]:
        """调用工具，返回归一化响应 ``{code, message, data, meta}``。

        - 未知工具 → ``UNKNOWN_TOOL``
        - 参数不合法 → ``INVALID_PARAM``（含缺少必填、类型不符、多余参数）
        - 网关/网络/鉴权错误 → 对应的 :class:`PmsError`
        """
        tool = self.spec.get(name)
        args = validate_arguments(tool, params)
        try:
            if self.is_mock:
                envelope = self.mock_backend.call(tool, args)
            else:
                self.config.check()
                envelope = self._dispatch(tool, args)
        except PmsError:
            raise
        except Exception as exc:  # 兜底，避免把未知异常抛给宿主
            raise internal_error(exc, tool=tool.name) from exc
        envelope.setdefault("meta", {})
        if isinstance(envelope["meta"], dict):
            envelope["meta"].setdefault("tool", tool.name)
            envelope["meta"].setdefault("interfaceCode", tool.code)
            envelope["meta"].setdefault("authMode", self.config.auth_mode)
        return envelope

    def _dispatch(self, tool: ToolSpec, args: Mapping[str, Any]) -> dict[str, Any]:
        """按 paramStyle / method 把参数分到 path、query、body。"""
        path_params = {key: value for key, value in args.items() if key in tool.path_param_names}
        rest = {key: value for key, value in args.items() if key not in path_params}
        style = (tool.param_style or "").lower()

        if style in ("query",):
            query, body = rest, None
        elif style in ("json_body", "json", "body", "jsonbody"):
            query, body = None, rest
        else:  # mixed / query_or_body：按方法就近选择
            if tool.method in ("POST", "PUT", "PATCH"):
                query, body = None, rest
            else:
                query, body = rest, None

        return self.transport.call(
            tool.method,
            tool.path,
            query=query,
            body=body,
            path_params=path_params,
            tool=tool.name,
        )

    # -- 便捷列表查询 ---------------------------------------------------
    def call_tool_list(self, name: str, params: Any = None) -> dict[str, Any]:
        """调用分页/列表类工具，额外附上 ``items`` / ``total`` 便于下游直接使用。"""
        envelope = self.call_tool(name, params)
        result = dict(envelope)
        items = extract_list(envelope)
        result["items"] = items
        result["total"] = extract_total(envelope) if extract_total(envelope) is not None else len(items)
        return result

    # -- 自检 -----------------------------------------------------------
    def doctor_report(self, probe: bool = True) -> dict[str, Any]:
        """收集环境/配置/规格自检信息（CLI doctor 直接输出）。"""
        config_problems = list(self.config.validate())
        spec_errors = list(self.spec.errors)
        problems = config_problems + spec_errors
        report: dict[str, Any] = {
            "ok": not problems,
            "python": sys.version.split()[0],
            "cwd": str(Path.cwd()),
            "config": self.config.describe(),
            "auth": self.auth.describe(),
            "spec": self.spec.info(),
            "groups": self.spec.group_summary(),
            "toolCount": len(self.spec.tools),
            "problems": problems,
            "warnings": list(self.spec.warnings),
            "mockProbe": None,
        }
        if probe and self.is_mock:
            report["mockProbe"] = self._probe_mock_tools()
            if report["mockProbe"].get("failed"):
                report["ok"] = False
                report["problems"].append(
                    f"mock 自检失败 {len(report['mockProbe']['failed'])} 个工具，详见 mockProbe.failed"
                )
        return report

    def _probe_mock_tools(self) -> dict[str, Any]:
        """在 mock 模式下把 26 个工具各调一次，校验 spec.mock 是否可用。"""
        failed: list[dict[str, Any]] = []
        ok_count = 0
        for tool in self.spec.tools:
            try:
                envelope = self.mock_backend.call(tool, tool.example_args())
                if envelope.get("code") != 0:
                    failed.append({"tool": tool.name, "error": f"code={envelope.get('code')}"})
                else:
                    ok_count += 1
            except PmsError as exc:
                failed.append({"tool": tool.name, "error": exc.to_dict()})
            except Exception as exc:  # pragma: no cover - 防御
                failed.append({"tool": tool.name, "error": f"{type(exc).__name__}: {exc}"})
        return {"total": len(self.spec.tools), "ok": ok_count, "failed": failed}

    # ===================================================================
    # 26 个工具的同名显式方法（方法名 = spec 工具名）
    # ===================================================================

    # -- 设备台账（5） ---------------------------------------------------
    def get_asset_by_id(self, assetId: str) -> dict[str, Any]:
        """根据资产ID查看设备台账详情。"""
        return self.call_tool("get_asset_by_id", {"assetId": assetId})

    def list_asset_params(
        self,
        assetType: str,
        stationId: str | None = None,
        voltageLevel: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询设备资产参数列表。"""
        return self.call_tool(
            "list_asset_params",
            filter_none(
                {
                    "assetType": assetType,
                    "stationId": stationId,
                    "voltageLevel": voltageLevel,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    def get_device_by_utc_num(self, utcNum: str) -> dict[str, Any]:
        """根据实物ID查看设备台账详情。"""
        return self.call_tool("get_device_by_utc_num", {"utcNum": utcNum})

    def list_psr_by_filters(
        self,
        stationId: str | None = None,
        voltageLevel: str | None = None,
        deviceType: str | None = None,
        name: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询电网设备台账列表。"""
        return self.call_tool(
            "list_psr_by_filters",
            filter_none(
                {
                    "stationId": stationId,
                    "voltageLevel": voltageLevel,
                    "deviceType": deviceType,
                    "name": name,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    def get_psr_by_id(self, psrId: str) -> dict[str, Any]:
        """根据资源ID查看设备台账详情。"""
        return self.call_tool("get_psr_by_id", {"psrId": psrId})

    # -- 设备树（2） ------------------------------------------------------
    def get_device_tree_root(self, orgId: str | None = None) -> dict[str, Any]:
        """查询设备树根节点。"""
        return self.call_tool("get_device_tree_root", filter_none({"orgId": orgId}))

    def get_device_tree_nodes(
        self,
        parentId: str,
        nodeType: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询设备树下级节点。"""
        return self.call_tool(
            "get_device_tree_nodes",
            filter_none({"parentId": parentId, "nodeType": nodeType, "pageNo": pageNo, "pageSize": pageSize}),
        )

    # -- 运维健康（4） ----------------------------------------------------
    def inquire_defect(
        self,
        stationId: str | None = None,
        deviceId: str | None = None,
        defectLevel: str | None = None,
        status: str | None = None,
        startTime: str | None = None,
        endTime: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询缺陷记录。"""
        return self.call_tool(
            "inquire_defect",
            filter_none(
                {
                    "stationId": stationId,
                    "deviceId": deviceId,
                    "defectLevel": defectLevel,
                    "status": status,
                    "startTime": startTime,
                    "endTime": endTime,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    def view_defect(self, defectId: str) -> dict[str, Any]:
        """查看缺陷记录。"""
        return self.call_tool("view_defect", {"defectId": defectId})

    def list_hazard(
        self,
        stationId: str | None = None,
        hazardType: str | None = None,
        riskLevel: str | None = None,
        status: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询隐患记录。"""
        return self.call_tool(
            "list_hazard",
            filter_none(
                {
                    "stationId": stationId,
                    "hazardType": hazardType,
                    "riskLevel": riskLevel,
                    "status": status,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    def list_fault_trip_records(
        self,
        deviceId: str | None = None,
        stationId: str | None = None,
        startTime: str | None = None,
        endTime: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询故障记录。"""
        return self.call_tool(
            "list_fault_trip_records",
            filter_none(
                {
                    "deviceId": deviceId,
                    "stationId": stationId,
                    "startTime": startTime,
                    "endTime": endTime,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    # -- 检修试验（6） ----------------------------------------------------
    def get_repair_plan(
        self,
        deviceId: str | None = None,
        stationId: str | None = None,
        year: int | None = None,
        month: int | None = None,
        planStatus: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询检修计划。"""
        return self.call_tool(
            "get_repair_plan",
            filter_none(
                {
                    "deviceId": deviceId,
                    "stationId": stationId,
                    "year": year,
                    "month": month,
                    "planStatus": planStatus,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    def find_repair_test(
        self,
        deviceId: str | None = None,
        startTime: str | None = None,
        endTime: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询修试记录。"""
        return self.call_tool(
            "find_repair_test",
            filter_none(
                {
                    "deviceId": deviceId,
                    "startTime": startTime,
                    "endTime": endTime,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    def find_repair_program(
        self,
        programId: str | None = None,
        deviceId: str | None = None,
        stationId: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询检修方案。"""
        return self.call_tool(
            "find_repair_program",
            filter_none(
                {
                    "programId": programId,
                    "deviceId": deviceId,
                    "stationId": stationId,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    def list_patrol_plan(
        self,
        stationId: str | None = None,
        startDate: str | None = None,
        endDate: str | None = None,
        status: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询巡视计划（工单）。"""
        return self.call_tool(
            "list_patrol_plan",
            filter_none(
                {
                    "stationId": stationId,
                    "startDate": startDate,
                    "endDate": endDate,
                    "status": status,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    def list_patrol_record(
        self,
        stationId: str | None = None,
        startDate: str | None = None,
        endDate: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询巡视记录。"""
        return self.call_tool(
            "list_patrol_record",
            filter_none(
                {
                    "stationId": stationId,
                    "startDate": startDate,
                    "endDate": endDate,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    def list_test_item(
        self,
        deviceType: str | None = None,
        testType: str | None = None,
        voltageLevel: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询检测试验项目。"""
        return self.call_tool(
            "list_test_item",
            filter_none(
                {
                    "deviceType": deviceType,
                    "testType": testType,
                    "voltageLevel": voltageLevel,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    # -- 可靠性（3） ------------------------------------------------------
    def query_station_scale_analysis(
        self,
        stationId: str | None = None,
        startDate: str | None = None,
        endDate: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """统计变电站可靠性分析数据。"""
        return self.call_tool(
            "query_station_scale_analysis",
            filter_none(
                {
                    "stationId": stationId,
                    "startDate": startDate,
                    "endDate": endDate,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    def query_outage_incident(
        self,
        stationId: str | None = None,
        voltageLevel: str | None = None,
        startTime: str | None = None,
        endTime: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询可靠性中压停电事件列表。"""
        return self.call_tool(
            "query_outage_incident",
            filter_none(
                {
                    "stationId": stationId,
                    "voltageLevel": voltageLevel,
                    "startTime": startTime,
                    "endTime": endTime,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    def query_open_capacity(
        self,
        deviceId: str | None = None,
        stationId: str | None = None,
        voltageLevel: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询设备可开放容量。"""
        return self.call_tool(
            "query_open_capacity",
            filter_none(
                {
                    "deviceId": deviceId,
                    "stationId": stationId,
                    "voltageLevel": voltageLevel,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    # -- 作业资源与图形拓扑（6） -----------------------------------------
    def find_smart_device(
        self,
        stationId: str | None = None,
        deviceType: str | None = None,
        onlineStatus: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询智能装备台账信息。"""
        return self.call_tool(
            "find_smart_device",
            filter_none(
                {
                    "stationId": stationId,
                    "deviceType": deviceType,
                    "onlineStatus": onlineStatus,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    def get_instrument_list(
        self,
        stationId: str | None = None,
        instrumentType: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询仪器仪表台账信息。"""
        return self.call_tool(
            "get_instrument_list",
            filter_none(
                {
                    "stationId": stationId,
                    "instrumentType": instrumentType,
                    "pageNo": pageNo,
                    "pageSize": pageSize,
                }
            ),
        )

    def get_manufacturer_infos(
        self,
        manufacturerName: str | None = None,
        pageNo: int | None = None,
        pageSize: int | None = None,
    ) -> dict[str, Any]:
        """查询生产厂家列表。"""
        return self.call_tool(
            "get_manufacturer_infos",
            filter_none({"manufacturerName": manufacturerName, "pageNo": pageNo, "pageSize": pageSize}),
        )

    def query_svg_map_by_psr_id(self, psrId: str) -> dict[str, Any]:
        """根据设备ID获取专题图。"""
        return self.call_tool("query_svg_map_by_psr_id", {"psrId": psrId})

    def search_power_path(
        self,
        psrId: str | None = None,
        deviceId: str | None = None,
    ) -> dict[str, Any]:
        """查询电源点和供电路径。"""
        return self.call_tool("search_power_path", filter_none({"psrId": psrId, "deviceId": deviceId}))

    def analyze_supply_area(
        self,
        psrId: str | None = None,
        deviceId: str | None = None,
        direction: str | None = None,
    ) -> dict[str, Any]:
        """分析供电范围。"""
        return self.call_tool(
            "analyze_supply_area",
            filter_none({"psrId": psrId, "deviceId": deviceId, "direction": direction}),
        )
