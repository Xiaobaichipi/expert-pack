"""接口规格：加载 ``spec/interfaces.json``，生成工具目录与 JSON Schema。

``interfaces.json`` 是本专家包 26 个 PMS 接口的**唯一事实源**：工具名、接口编码、
路径、方法、参数、mock 数据、分组都在这里定义。正式《接口说明文档》下发后只改
该文件，本模块与 client / mcp_server / pms_cli 均无需改动。

本模块提供：

- :class:`ParamSpec` / :class:`ToolSpec` / :class:`InterfaceSpec`
- :func:`load_spec`            按路径/环境变量定位并加载（失败给出可操作报错）
- :class:`InterfaceSpec` 的 ``tool_schemas()`` 直接用于 MCP ``tools/list``
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .config import find_spec_path
from .errors import ErrorCode, PmsError, spec_error, unknown_tool

#: 允许的 HTTP 方法
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
#: spec 中参数类型 → JSON Schema 类型
_PARAM_TYPE_MAP = {
    "string": "string",
    "integer": "integer",
    "int": "integer",
    "number": "number",
    "float": "number",
    "double": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "array": "array",
    "object": "object",
}


def json_schema_type(param_type: str) -> str:
    """把 spec 里的参数类型映射为 JSON Schema type。"""
    return _PARAM_TYPE_MAP.get(str(param_type or "string").lower(), "string")


@dataclass(frozen=True)
class ParamSpec:
    """单个入参定义。"""

    name: str
    type: str
    required: bool
    desc: str
    location: str = "query"  # path / query / body
    default: Any = None
    example: Any = None
    enum: tuple = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def json_type(self) -> str:
        return json_schema_type(self.type)

    def to_schema(self) -> dict[str, Any]:
        """生成 JSON Schema 属性定义。"""
        description = self.desc or self.name
        if self.example is not None:
            description = f"{description}（示例：{self.example}）"
        schema: dict[str, Any] = {"type": self.json_type, "description": description}
        if self.default is not None:
            schema["default"] = self.default
        if self.enum:
            schema["enum"] = list(self.enum)
        return schema

    def example_value(self) -> Any:
        if self.example is not None:
            return self.example
        if self.default is not None:
            return self.default
        return None


class ToolSpec:
    """一个 MCP 工具（对应一个 PMS 接口）。"""

    def __init__(
        self,
        raw: Mapping[str, Any],
        *,
        group_title: str = "",
        group_skill: str = "",
        group_role: str = "",
        defaults: Mapping[str, Any] | None = None,
    ) -> None:
        self.raw: dict[str, Any] = dict(raw)
        self.defaults: dict[str, Any] = dict(defaults or {})
        self.name = str(raw.get("name") or "")
        self.code = str(raw.get("code") or "")
        self.title = str(raw.get("title") or "")
        self.group = str(raw.get("group") or "")
        self.group_title = group_title
        self.group_skill = group_skill
        self.group_role = group_role
        self.method = str(raw.get("method") or "GET").upper()
        self.path = str(raw.get("path") or "")
        self.param_style = str(raw.get("paramStyle") or self.defaults.get("paramStyle") or "query_or_body")
        self.response_hint: dict[str, Any] = dict(raw.get("responseHint") or {})
        self.typical_questions: list[str] = list(raw.get("typicalQuestions") or [])
        self.mock: Any = raw.get("mock")
        self.params: list[ParamSpec] = []
        for item in raw.get("params") or []:
            if not isinstance(item, Mapping):
                continue
            location = str(item.get("in") or "query")
            self.params.append(
                ParamSpec(
                    name=str(item.get("name") or ""),
                    type=str(item.get("type") or "string"),
                    required=bool(item.get("required")),
                    desc=str(item.get("desc") or ""),
                    location=location,
                    default=item.get("default"),
                    example=item.get("example"),
                    enum=tuple(item.get("enum") or ()),
                    raw=dict(item),
                )
            )

    # -- 参数视图 -------------------------------------------------------
    @property
    def required_params(self) -> list[ParamSpec]:
        return [param for param in self.params if param.required]

    @property
    def optional_params(self) -> list[ParamSpec]:
        return [param for param in self.params if not param.required]

    @property
    def path_param_names(self) -> list[str]:
        return [param.name for param in self.params if param.location == "path"]

    @property
    def is_paged(self) -> bool:
        return str(self.response_hint.get("kind") or "").lower() in ("paged", "list")

    @property
    def is_mockable(self) -> bool:
        return self.mock is not None

    # -- JSON Schema ----------------------------------------------------
    def input_schema(self) -> dict[str, Any]:
        """生成 MCP ``tools/list`` 所需的 inputSchema。"""
        properties = {param.name: param.to_schema() for param in self.params}
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "required": [param.name for param in self.required_params],
            "additionalProperties": False,
        }
        if not properties:
            schema["description"] = "该接口无需入参"
        return schema

    def description(self, max_length: int = 480) -> str:
        """工具描述：用途 + 接口编码 + 分组 + 典型问数 + 关键参数。"""
        parts: list[str] = [f"{self.title}。"]
        parts.append(f"接口编码 {self.code}，分组「{self.group_title or self.group}」，{self.method} {self.path}。")
        if self.typical_questions:
            parts.append("典型问数：" + "；".join(self.typical_questions) + "。")
        if self.params:
            param_text = "；".join(
                f"{param.name}({param.json_type}{'，必填' if param.required else ''})" for param in self.params
            )
            parts.append("参数：" + param_text + "。")
        text = "".join(parts)
        if len(text) > max_length:
            text = text[: max_length - 1] + "…"
        return text

    def example_args(self) -> dict[str, Any]:
        """可用于 CLI 示例 / describe 的参数示例（必填项 + 有默认值的可选项）。"""
        example: dict[str, Any] = {}
        for param in self.params:
            value = param.example_value()
            if param.required:
                example[param.name] = value if value is not None else f"<{param.name}>"
            elif value is not None:
                example[param.name] = value
        return example

    def mock_sample(self) -> Any:
        """mock 数据样例（分页接口取第一条，便于阅读）。"""
        if isinstance(self.mock, Mapping) and self.is_paged:
            for key in ("list", "records"):
                items = self.mock.get(key)
                if isinstance(items, list) and items:
                    return items[0]
            return self.mock
        return self.mock

    # -- 序列化 ---------------------------------------------------------
    def to_mcp_tool(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description(), "inputSchema": self.input_schema()}

    def describe(self) -> dict[str, Any]:
        """CLI ``describe`` 输出。"""
        return {
            "name": self.name,
            "title": self.title,
            "code": self.code,
            "group": self.group,
            "groupTitle": self.group_title,
            "groupSkill": self.group_skill,
            "groupRole": self.group_role,
            "method": self.method,
            "path": self.path,
            "paramStyle": self.param_style,
            "params": [
                {
                    "name": param.name,
                    "type": param.json_type,
                    "required": param.required,
                    "in": param.location,
                    "desc": param.desc,
                    **({"default": param.default} if param.default is not None else {}),
                    **({"example": param.example} if param.example is not None else {}),
                }
                for param in self.params
            ],
            "required": [param.name for param in self.required_params],
            "inputSchema": self.input_schema(),
            "responseHint": self.response_hint,
            "typicalQuestions": self.typical_questions,
            "exampleParams": self.example_args(),
            "mockSample": self.mock_sample(),
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"ToolSpec(name={self.name!r}, code={self.code!r}, group={self.group!r})"


class InterfaceSpec:
    """整份接口规格（26 个工具 + 6 个分组 + 默认配置）。"""

    def __init__(self, raw: Mapping[str, Any], *, path: str | Path | None = None) -> None:
        self.raw: dict[str, Any] = dict(raw)
        self.path: Path | None = Path(path).resolve() if path else None
        self.spec_version = str(raw.get("specVersion") or "")
        self.pack_slug = str(raw.get("packSlug") or "")
        self.pack_display_name = str(raw.get("packDisplayName") or "")
        self.source_doc = str(raw.get("sourceDoc") or "")
        self.status = str(raw.get("status") or "")
        self.note = str(raw.get("note") or "")
        self.defaults: dict[str, Any] = dict(raw.get("defaults") or {})
        self.groups: list[dict[str, Any]] = [dict(item) for item in raw.get("groups") or []]
        self._group_by_id = {str(item.get("id")): item for item in self.groups}

        tools_raw = raw.get("tools")
        if not isinstance(tools_raw, list) or not tools_raw:
            raise spec_error("接口规格文件缺少 tools 数组或为空，无法构建任何工具")

        self.tools: list[ToolSpec] = []
        self._by_name: dict[str, ToolSpec] = {}
        for item in tools_raw:
            if not isinstance(item, Mapping):
                raise spec_error(f"tools 中存在非对象元素：{item!r}")
            group_id = str(item.get("group") or "")
            group = self._group_by_id.get(group_id, {})
            tool = ToolSpec(
                item,
                group_title=str(group.get("title") or ""),
                group_skill=str(group.get("skill") or ""),
                group_role=str(group.get("role") or ""),
                defaults=self.defaults,
            )
            self.tools.append(tool)
            self._by_name[tool.name] = tool

        self.errors: list[str] = []
        self.warnings: list[str] = []
        self._validate()

    # -- 加载 -----------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path | None = None) -> "InterfaceSpec":
        spec_path = find_spec_path(str(path) if path else None)
        try:
            text = spec_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise spec_error(f"无法读取接口规格文件 {spec_path}：{exc}") from None
        try:
            raw = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise spec_error(f"接口规格文件不是合法 JSON：{spec_path}（{exc}）") from None
        if not isinstance(raw, Mapping):
            raise spec_error(f"接口规格文件根节点必须是对象：{spec_path}")
        spec = cls(raw, path=spec_path)
        if spec.errors:
            raise spec_error(
                "接口规格文件校验失败，请修正 expert-pack/spec/interfaces.json：\n  - "
                + "\n  - ".join(spec.errors),
                details={"errors": spec.errors},
            )
        return spec

    # -- 校验 -----------------------------------------------------------
    def _validate(self) -> None:
        seen_names: set[str] = set()
        seen_codes: set[str] = set()
        for tool in self.tools:
            label = tool.name or "<未命名工具>"
            for attr in ("name", "code", "title", "group", "path"):
                if not getattr(tool, attr):
                    self.errors.append(f"工具 {label} 缺少必填字段 {attr}")
            if tool.method not in HTTP_METHODS:
                self.errors.append(f"工具 {label} 的 method={tool.method!r} 不支持（可选 {', '.join(HTTP_METHODS)}）")
            if tool.name in seen_names:
                self.errors.append(f"工具名重复：{tool.name}")
            seen_names.add(tool.name)
            if tool.code in seen_codes:
                self.errors.append(f"接口编码重复：{tool.code}（工具 {tool.name}）")
            seen_codes.add(tool.code)
            if tool.group and tool.group not in self._group_by_id:
                self.errors.append(f"工具 {label} 引用了未定义的分组 {tool.group!r}")
            if not tool.is_mockable:
                self.errors.append(f"工具 {label} 缺少 mock 数据（mock 模式依赖它出数）")
            if not tool.response_hint:
                self.warnings.append(f"工具 {label} 未定义 responseHint，分页/list 提取将依赖运行时返回结构")
            param_names: set[str] = set()
            for param in tool.params:
                if not param.name:
                    self.errors.append(f"工具 {label} 存在未命名参数")
                    continue
                if param.name in param_names:
                    self.errors.append(f"工具 {label} 参数名重复：{param.name}")
                param_names.add(param.name)
                if param.location not in ("path", "query", "body", "header"):
                    self.errors.append(f"工具 {label} 参数 {param.name} 的 in={param.location!r} 不支持")
                if param.location == "path" and "{" + param.name + "}" not in tool.path:
                    self.errors.append(f"工具 {label} 参数 {param.name} 声明为 path 参数，但 path 中无对应占位符")

        for group in self.groups:
            gid = str(group.get("id") or "")
            actual = len([tool for tool in self.tools if tool.group == gid])
            declared = group.get("toolCount")
            if declared is not None and int(declared) != actual:
                self.warnings.append(f"分组 {gid} 声明 toolCount={declared}，实际工具数为 {actual}")
        if self.status and self.status != "confirmed":
            self.warnings.append(
                f"接口规格 status={self.status}：接口地址/参数为推断占位，正式《接口说明文档》下发后需核对 spec/interfaces.json"
            )

    # -- 查询 -----------------------------------------------------------
    def get(self, name: str) -> ToolSpec:
        """按工具名取定义，未知工具抛出带建议的 PmsError。"""
        if not isinstance(name, str) or not name.strip():
            raise PmsError(ErrorCode.INVALID_PARAM, "工具名不能为空，请先执行 tools/list 或 CLI list-tools 查看可用工具")
        tool = self._by_name.get(name.strip())
        if tool is None:
            raise unknown_tool(name, list(self._by_name))
        return tool

    def has(self, name: str) -> bool:
        return name in self._by_name

    @property
    def tool_names(self) -> list[str]:
        return [tool.name for tool in self.tools]

    @property
    def group_titles(self) -> dict[str, str]:
        return {str(group.get("id")): str(group.get("title") or "") for group in self.groups}

    def group_counts(self) -> dict[str, int]:
        counts = {str(group.get("id")): 0 for group in self.groups}
        for tool in self.tools:
            counts[tool.group] = counts.get(tool.group, 0) + 1
        return counts

    def group_summary(self) -> list[dict[str, Any]]:
        counts = self.group_counts()
        summary = []
        for group in self.groups:
            gid = str(group.get("id") or "")
            summary.append(
                {
                    "id": gid,
                    "title": group.get("title") or "",
                    "skill": group.get("skill") or "",
                    "role": group.get("role") or "",
                    "toolCount": counts.get(gid, 0),
                }
            )
        return summary

    def tool_schemas(self) -> list[dict[str, Any]]:
        """MCP ``tools/list`` 返回的 tools 数组。"""
        return [tool.to_mcp_tool() for tool in self.tools]

    def info(self) -> dict[str, Any]:
        return {
            "specVersion": self.spec_version,
            "packSlug": self.pack_slug,
            "packDisplayName": self.pack_display_name,
            "sourceDoc": self.source_doc,
            "status": self.status,
            "toolCount": len(self.tools),
            "groupCount": len(self.groups),
            "specPath": str(self.path) if self.path else None,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def load_spec(path: str | Path | None = None) -> InterfaceSpec:
    """便捷函数：等价于 :meth:`InterfaceSpec.load`。"""
    return InterfaceSpec.load(path)
