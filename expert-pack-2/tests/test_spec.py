"""spec/interfaces.json 完整性测试：26 个工具、唯一性、分组、JSON Schema 正确性。"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import json
import unittest

from _support import (
    EXPECTED_GROUP_COUNTS,
    EXPECTED_TOOL_COUNT,
    SPEC_PATH,
    BaseTestCase,
    load_spec,
)
from pms_client import ErrorCode, PmsError
from pms_client.spec import json_schema_type


class SpecIntegrityTest(BaseTestCase):
    def test_spec_file_exists_and_is_utf8_json(self) -> None:
        self.assertTrue(SPEC_PATH.is_file(), f"spec 文件不存在：{SPEC_PATH}")
        raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        self.assertEqual(raw["packSlug"], "bianya-intelligent-data-qa")
        self.assertEqual(len(raw["tools"]), EXPECTED_TOOL_COUNT)

    def test_tool_count_is_26(self) -> None:
        self.assertEqual(len(self.spec.tools), EXPECTED_TOOL_COUNT)
        self.assertEqual(len(self.spec.tool_names), EXPECTED_TOOL_COUNT)

    def test_tool_names_unique(self) -> None:
        names = [tool.name for tool in self.spec.tools]
        self.assertEqual(len(set(names)), len(names), "存在重复工具名")
        names_lower = [name.lower() for name in names]
        self.assertEqual(len(set(names_lower)), len(names), "工具名大小写重复")

    def test_interface_codes_unique(self) -> None:
        codes = [tool.code for tool in self.spec.tools]
        self.assertEqual(len(set(codes)), len(codes), "存在重复接口编码")
        for code in codes:
            self.assertRegex(code, r"^pgp-\d{3}-\d{4}-\d{5}$", f"接口编码格式异常：{code}")

    def test_group_counts_match_declaration(self) -> None:
        self.assertEqual(self.spec.group_counts(), EXPECTED_GROUP_COUNTS)
        self.assertEqual(sum(EXPECTED_GROUP_COUNTS.values()), EXPECTED_TOOL_COUNT)
        for group in self.spec.groups:
            self.assertEqual(group["toolCount"], EXPECTED_GROUP_COUNTS[group["id"]])
        for tool in self.spec.tools:
            self.assertIn(tool.group, EXPECTED_GROUP_COUNTS)

    def test_group_metadata_complete(self) -> None:
        summary = self.spec.group_summary()
        self.assertEqual(len(summary), 6)
        for item in summary:
            self.assertTrue(item["title"])
            self.assertTrue(item["skill"].startswith("substation-"))
            self.assertTrue(item["role"])
            self.assertGreater(item["toolCount"], 0)

    def test_each_tool_has_required_fields(self) -> None:
        for tool in self.spec.tools:
            with self.subTest(tool=tool.name):
                self.assertTrue(tool.name)
                self.assertTrue(tool.code)
                self.assertTrue(tool.title)
                self.assertTrue(tool.group)
                self.assertIn(tool.method, ("GET", "POST"))
                self.assertTrue(tool.path.startswith("/"))
                self.assertTrue(tool.response_hint)
                self.assertTrue(tool.typical_questions)
                self.assertIsNotNone(tool.mock)
                self.assertTrue(tool.description())

    def test_path_placeholders_have_params(self) -> None:
        for tool in self.spec.tools:
            for name in tool.path_param_names:
                self.assertIn("{" + name + "}", tool.path, f"{tool.name} 的 path 参数 {name} 没有占位符")
            for param in tool.params:
                if param.location == "path":
                    self.assertIn("{" + param.name + "}", tool.path)
                    self.assertTrue(param.required, f"{tool.name} 的 path 参数 {param.name} 应为必填")

    def test_no_duplicate_param_names(self) -> None:
        for tool in self.spec.tools:
            names = [param.name for param in tool.params]
            self.assertEqual(len(set(names)), len(names), f"{tool.name} 参数名重复")

    def test_input_schema_structure(self) -> None:
        for tool in self.spec.tools:
            with self.subTest(tool=tool.name):
                schema = tool.input_schema()
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])
                expected_required = [param.name for param in tool.params if param.required]
                self.assertEqual(schema["required"], expected_required)
                self.assertEqual(set(schema["properties"]), {param.name for param in tool.params})
                for prop in schema["properties"].values():
                    self.assertIn(prop["type"], ("string", "integer", "number", "boolean", "array", "object"))
                    self.assertTrue(prop["description"])

    def test_input_schema_examples_and_defaults(self) -> None:
        tool = self.spec.get("get_asset_by_id")
        schema = tool.input_schema()
        self.assertEqual(schema["required"], ["assetId"])
        self.assertIn("AST-102-0001", schema["properties"]["assetId"]["description"])

        tool = self.spec.get("list_asset_params")
        schema = tool.input_schema()
        self.assertEqual(schema["required"], ["assetType"])
        self.assertEqual(schema["properties"]["pageNo"]["type"], "integer")
        self.assertEqual(schema["properties"]["pageNo"]["default"], 1)
        self.assertEqual(schema["properties"]["pageSize"]["default"], 20)

    def test_tool_types_are_json_schema_compatible(self) -> None:
        for tool in self.spec.tools:
            for param in tool.params:
                self.assertIn(json_schema_type(param.type), ("string", "integer", "number", "boolean", "array", "object"))

    def test_tool_schemas_for_mcp_tools_list(self) -> None:
        schemas = self.spec.tool_schemas()
        self.assertEqual(len(schemas), EXPECTED_TOOL_COUNT)
        self.assertEqual([item["name"] for item in schemas], self.spec.tool_names)
        for item in schemas:
            self.assertEqual(set(item), {"name", "description", "inputSchema"})
            self.assertLessEqual(len(item["description"]), 480)

    def test_example_args_cover_required_params(self) -> None:
        for tool in self.spec.tools:
            example = tool.example_args()
            for param in tool.required_params:
                self.assertIn(param.name, example, f"{tool.name} 示例参数缺少必填项 {param.name}")
                self.assertNotEqual(example[param.name], "")

    def test_all_tools_have_mock_payload(self) -> None:
        for tool in self.spec.tools:
            self.assertIsNotNone(tool.mock, f"{tool.name} 缺少 mock")
            if tool.is_paged:
                self.assertIn("list", tool.mock, f"{tool.name} 分页 mock 缺少 list")
                self.assertTrue(isinstance(tool.mock["list"], list))

    def test_spec_validation_has_no_errors(self) -> None:
        self.assertEqual(self.spec.errors, [], f"spec 校验错误：{self.spec.errors}")
        self.assertTrue(any("inferred" in warning for warning in self.spec.warnings))

    def test_unknown_tool_raises_helpful_error(self) -> None:
        with self.assertRaises(PmsError) as ctx:
            self.spec.get("no_such_tool")
        self.assertEqual(ctx.exception.code, ErrorCode.UNKNOWN_TOOL)
        with self.assertRaises(PmsError):
            self.spec.get("get_asset_by_id_typo")
        # 近似名字应给出建议
        with self.assertRaises(PmsError) as ctx:
            self.spec.get("get_asset_by_ids")
        self.assertIn("get_asset_by_id", ctx.exception.message)

    def test_spec_info(self) -> None:
        info = self.spec.info()
        self.assertEqual(info["toolCount"], EXPECTED_TOOL_COUNT)
        self.assertEqual(info["groupCount"], 6)
        self.assertEqual(info["packDisplayName"], "变电智能问数")
        self.assertEqual(info["errors"], [])

    def test_tool_lookup_by_name_is_stable(self) -> None:
        tool = self.spec.get("query_svg_map_by_psr_id")
        self.assertEqual(tool.code, "pgp-103-2411-00502")
        self.assertTrue(self.spec.has("query_svg_map_by_psr_id"))
        self.assertFalse(self.spec.has("nope"))
        self.assertEqual(tool.path_param_names, [])

    def test_loading_spec_from_explicit_path(self) -> None:
        spec = load_spec()
        self.assertEqual(len(spec.tools), EXPECTED_TOOL_COUNT)
        other = load_spec()
        self.assertEqual(spec.tool_names, other.tool_names)


if __name__ == "__main__":
    unittest.main()
