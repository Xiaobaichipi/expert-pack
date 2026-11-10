"""mock 模式测试：26 个工具同名方法、分页、过滤、深拷贝隔离、参数归一。"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import unittest

from _support import BaseTestCase
from pms_client import ErrorCode, PmsError
from pms_client.client import validate_arguments
from pms_client.mock import MockBackend
from pms_client.spec import ToolSpec
from pms_client.transport import extract_list, extract_total


class MockCallTest(BaseTestCase):
    def test_call_asset_by_id(self) -> None:
        resp = self.client.call_tool("get_asset_by_id", {"assetId": "AST-102-0001"})
        self.assertEqual(resp["code"], 0)
        self.assertIn("mock", resp["message"])
        self.assertEqual(resp["data"]["assetName"], "1号主变")
        self.assertEqual(resp["data"]["psrId"], "PSR-220-0001")
        self.assertEqual(resp["meta"]["mode"], "mock")
        self.assertEqual(resp["meta"]["interfaceCode"], "pgp-102-2411-00102")
        self.assertFalse(resp["meta"]["paged"])

    def test_every_tool_has_explicit_method(self) -> None:
        missing = [tool.name for tool in self.spec.tools if not callable(getattr(type(self.client), tool.name, None))]
        self.assertEqual(missing, [], f"缺少同名显式方法：{missing}")
        # 显式方法数量不能靠 __getattr__ 混淆：每个方法都必须真实定义在类上
        for tool in self.spec.tools:
            self.assertTrue(hasattr(type(self.client), tool.name))

    def test_all_26_explicit_methods_return_mock_data(self) -> None:
        for tool in self.spec.tools:
            with self.subTest(tool=tool.name):
                method = getattr(self.client, tool.name)
                resp = method(**tool.example_args())
                self.assertEqual(resp["code"], 0)
                self.assertIsNotNone(resp.get("data"))
                self.assertEqual(resp["meta"]["tool"], tool.name)

    def test_all_26_call_tool_paths(self) -> None:
        for tool in self.spec.tools:
            with self.subTest(tool=tool.name):
                resp = self.client.call_tool(tool.name, tool.example_args())
                self.assertEqual(resp["code"], 0)

    def test_object_mock_is_deep_copied(self) -> None:
        first = self.client.call_tool("get_asset_by_id", {"assetId": "AST-102-0001"})
        first["data"]["assetName"] = "被篡改"
        second = self.client.call_tool("get_asset_by_id", {"assetId": "AST-102-0001"})
        self.assertEqual(second["data"]["assetName"], "1号主变")
        self.assertEqual(self.spec.get("get_asset_by_id").mock["assetName"], "1号主变")

    def test_params_accept_json_string(self) -> None:
        resp = self.client.call_tool("get_asset_by_id", '{"assetId": "AST-102-0001"}')
        self.assertEqual(resp["data"]["assetId"], "AST-102-0001")

    def test_params_none_for_optional_only_tool(self) -> None:
        resp = self.client.get_device_tree_root()
        self.assertEqual(resp["data"]["nodeName"], "河南电网设备树")


class MockPagingTest(BaseTestCase):
    def test_paging_first_page(self) -> None:
        resp = self.client.call_tool("list_asset_params", {"assetType": "transformer", "pageSize": 1})
        self.assertEqual(resp["data"]["total"], 2)
        self.assertEqual(resp["data"]["pageNo"], 1)
        self.assertEqual(resp["data"]["pageSize"], 1)
        self.assertEqual(len(resp["data"]["list"]), 1)
        self.assertEqual(resp["data"]["list"][0]["assetId"], "AST-102-0001")

    def test_paging_second_page(self) -> None:
        resp = self.client.list_asset_params("transformer", pageNo=2, pageSize=1)
        self.assertEqual(resp["data"]["pageNo"], 2)
        self.assertEqual(len(resp["data"]["list"]), 1)
        self.assertEqual(resp["data"]["list"][0]["assetId"], "AST-102-0002")

    def test_paging_beyond_last_page(self) -> None:
        resp = self.client.list_asset_params("transformer", pageNo=99, pageSize=10)
        self.assertEqual(resp["data"]["total"], 2)
        self.assertEqual(resp["data"]["list"], [])

    def test_default_paging_from_spec(self) -> None:
        resp = self.client.call_tool("list_psr_by_filters", {})
        self.assertEqual(resp["data"]["pageNo"], 1)
        self.assertEqual(resp["data"]["pageSize"], 20)
        self.assertEqual(resp["data"]["total"], 2)

    def test_empty_string_page_params_use_defaults(self) -> None:
        resp = self.client.call_tool("list_psr_by_filters", {"pageNo": None, "pageSize": None})
        self.assertEqual(resp["data"]["pageNo"], 1)

    def test_extract_list_and_total(self) -> None:
        resp = self.client.call_tool("inquire_defect", {"pageSize": 1})
        items = extract_list(resp)
        self.assertEqual(len(items), 1)
        self.assertEqual(extract_total(resp), 2)
        self.assertEqual(resp["data"]["total"], 2)


class MockFilterTest(BaseTestCase):
    def test_filter_exact_enum(self) -> None:
        resp = self.client.list_psr_by_filters(deviceType="变压器")
        self.assertEqual(resp["data"]["total"], 1)
        self.assertEqual(resp["data"]["list"][0]["psrName"], "1号主变")

    def test_filter_contains_via_alias(self) -> None:
        resp = self.client.list_psr_by_filters(name="断路器")
        self.assertEqual(resp["data"]["total"], 1)
        self.assertEqual(resp["data"]["list"][0]["psrName"], "2201断路器")

    def test_filter_no_match_returns_empty(self) -> None:
        resp = self.client.list_psr_by_filters(deviceType="不存在类型")
        self.assertEqual(resp["data"]["total"], 0)
        self.assertEqual(resp["data"]["list"], [])

    def test_filter_on_second_level_field(self) -> None:
        resp = self.client.find_smart_device(onlineStatus="在线")
        self.assertEqual(resp["data"]["total"], 1)
        self.assertEqual(resp["data"]["list"][0]["deviceId"], "SD-001")

    def test_filter_with_paging_together(self) -> None:
        resp = self.client.inquire_defect(defectLevel="一般", pageSize=10)
        self.assertEqual(resp["data"]["total"], 1)
        self.assertEqual(resp["data"]["list"][0]["defectNo"], "QXB-2026-0002")

    def test_filter_ignores_unknown_field(self) -> None:
        # stationId 在 mock 数据中不存在，应视为不过滤而不是过滤掉全部
        resp = self.client.inquire_defect(stationId="STA-220-01")
        self.assertEqual(resp["data"]["total"], 2)

    def test_filter_station_name_contains(self) -> None:
        # stationName 不是接口入参，但 MockBackend 支持按样例字段直接过滤（供联调/演示）
        backend = MockBackend(self.spec)
        envelope = backend.call(self.spec.get("list_hazard"), {"stationName": "郑州"})
        self.assertEqual(envelope["data"]["total"], 1)
        self.assertEqual(envelope["data"]["list"][0]["hazardId"], "HZ-2026-0001")


class MockEnvelopeTest(BaseTestCase):
    def test_paged_meta_flag(self) -> None:
        resp = self.client.call_tool("list_test_item", {})
        self.assertTrue(resp["meta"]["paged"])
        self.assertEqual(resp["meta"]["authMode"], "mock")
        self.assertEqual(resp["meta"]["interfaceCode"], "pgp-106-2411-06801")

    def test_mock_without_data_raises_mock_error(self) -> None:
        raw = dict(self.spec.get("get_asset_by_id").raw)
        raw.pop("mock", None)
        tool = ToolSpec(raw)
        with self.assertRaises(PmsError) as ctx:
            MockBackend(self.spec).call(tool, {"assetId": "AST-102-0001"})
        self.assertEqual(ctx.exception.code, ErrorCode.MOCK_ERROR)

    def test_mock_preview(self) -> None:
        backend = MockBackend(self.spec)
        preview = backend.preview(self.spec.get("list_psr_by_filters"))
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]["psrId"], "PSR-220-0001")

    def test_invalid_mock_structure_raises(self) -> None:
        raw = dict(self.spec.get("list_psr_by_filters").raw)
        raw["mock"] = "not-a-list"
        tool = ToolSpec(raw)
        with self.assertRaises(PmsError) as ctx:
            MockBackend(self.spec).call(tool, {})
        self.assertEqual(ctx.exception.code, ErrorCode.MOCK_ERROR)


class ArgumentValidationTest(BaseTestCase):
    def test_unknown_tool(self) -> None:
        with self.assertRaises(PmsError) as ctx:
            self.client.call_tool("bogus_tool", {})
        self.assertEqual(ctx.exception.code, ErrorCode.UNKNOWN_TOOL)

    def test_missing_required_param(self) -> None:
        with self.assertRaises(PmsError) as ctx:
            self.client.call_tool("get_asset_by_id", {})
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_PARAM)
        self.assertIn("assetId", ctx.exception.message)
        self.assertIn("assetId", ctx.exception.details["missing"])

    def test_empty_required_param(self) -> None:
        with self.assertRaises(PmsError) as ctx:
            self.client.call_tool("get_asset_by_id", {"assetId": "  "})
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_PARAM)

    def test_unknown_param_rejected(self) -> None:
        with self.assertRaises(PmsError) as ctx:
            self.client.call_tool("get_asset_by_id", {"assetId": "AST-102-0001", "foo": "bar"})
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_PARAM)
        self.assertIn("foo", ctx.exception.message)

    def test_params_must_be_mapping(self) -> None:
        with self.assertRaises(PmsError) as ctx:
            self.client.call_tool("get_asset_by_id", ["AST-102-0001"])
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_PARAM)

    def test_params_invalid_json_string(self) -> None:
        with self.assertRaises(PmsError) as ctx:
            self.client.call_tool("get_asset_by_id", "{not json}")
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_PARAM)

    def test_type_coercion_integer(self) -> None:
        tool = self.spec.get("list_psr_by_filters")
        args = validate_arguments(tool, {"pageNo": "2", "pageSize": 5})
        self.assertEqual(args, {"pageNo": 2, "pageSize": 5})

    def test_type_coercion_string(self) -> None:
        tool = self.spec.get("get_asset_by_id")
        args = validate_arguments(tool, {"assetId": 12345})
        self.assertEqual(args, {"assetId": "12345"})

    def test_type_error_integer(self) -> None:
        with self.assertRaises(PmsError) as ctx:
            self.client.call_tool("list_psr_by_filters", {"pageNo": "abc"})
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_PARAM)

    def test_none_optionals_dropped(self) -> None:
        optional_tool = self.spec.get("get_device_tree_root")
        self.assertEqual(validate_arguments(optional_tool, None), {})
        self.assertEqual(validate_arguments(optional_tool, {"orgId": None}), {})
        paged_tool = self.spec.get("list_psr_by_filters")
        self.assertEqual(validate_arguments(paged_tool, {"pageNo": None, "pageSize": None}), {})
        required_tool = self.spec.get("get_asset_by_id")
        self.assertEqual(validate_arguments(required_tool, {"assetId": "A1"}), {"assetId": "A1"})

    def test_array_type_validation(self) -> None:
        params = {"deviceIds": ["A1", "A2"]}
        tool = ToolSpec(
            {
                "name": "fake_array_tool",
                "code": "pgp-000-0000-00000",
                "title": "数组参数工具",
                "group": "asset-ledger",
                "method": "POST",
                "path": "/fake",
                "params": [{"name": "deviceIds", "type": "array", "required": True}],
                "mock": [],
            }
        )
        self.assertEqual(validate_arguments(tool, params), params)


if __name__ == "__main__":
    unittest.main()
