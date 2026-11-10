"""错误归一 / 响应归一 / 传输层 / 鉴权 / 配置 测试（不访问真实网络，urlopen 全部打桩）。"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import hashlib
import hmac
import io
import json
import socket
import unittest
import urllib.error
from unittest import mock

from _support import SPEC_PATH, BaseTestCase, make_config
from pms_client import AuthProvider, ErrorCode, PmsClient, PmsConfig, PmsError
from pms_client.auth import (
    AppKeyAuthProvider,
    MockAuthProvider,
    NoneAuthProvider,
    TokenAuthProvider,
    build_appkey_signature,
    create_auth_provider,
)
from pms_client.config import find_spec_path
from pms_client.signing import canonical_query
from pms_client.transport import (
    encode_query,
    extract_list,
    extract_total,
    normalize_envelope,
    substitute_path,
)
from pms_client import errors as pms_errors


class FakeResponse:
    def __init__(self, payload, status: int = 200) -> None:
        if isinstance(payload, (bytes, bytearray)):
            self._body = bytes(payload)
        elif isinstance(payload, str):
            self._body = payload.encode("utf-8")
        else:
            self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args) -> bool:
        return False


class FakeOpener:
    """按顺序返回预置响应/异常，并记录收到的 Request。"""

    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=None, context=None):
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, BaseException):
            raise item
        return item


def token_client(**overrides) -> PmsClient:
    """构造一个真实模式（token 鉴权）客户端，网络层由测试打桩。"""
    params = {
        "base_url": "https://gw.example.com",
        "auth_mode": "token",
        "token": "test-token",
        "timeout": 5.0,
        "retry": 0,
        "spec_path": str(SPEC_PATH),
    }
    params.update(overrides)
    return PmsClient(PmsConfig(**params))


class PmsErrorTest(unittest.TestCase):
    def test_to_dict_minimal(self) -> None:
        error = PmsError(ErrorCode.UNKNOWN_TOOL, "找不到工具")
        self.assertEqual(error.to_dict(), {"code": "UNKNOWN_TOOL", "message": "找不到工具"})
        self.assertFalse(error.retryable)
        self.assertIsNone(error.http_status)

    def test_to_dict_full(self) -> None:
        error = PmsError(
            ErrorCode.SERVER_ERROR,
            "网关 500",
            http_status=500,
            retryable=True,
            details={"x": 1},
            tool="get_asset_by_id",
        )
        payload = error.to_dict()
        self.assertEqual(payload["httpStatus"], 500)
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["tool"], "get_asset_by_id")
        self.assertEqual(payload["details"], {"x": 1})
        self.assertIn("SERVER_ERROR", str(error))

    def test_http_error_mapping(self) -> None:
        cases = {
            401: (ErrorCode.AUTH_FAILED, False),
            403: (ErrorCode.AUTH_FAILED, False),
            404: (ErrorCode.NOT_FOUND, False),
            400: (ErrorCode.BAD_REQUEST, False),
            422: (ErrorCode.BAD_REQUEST, False),
            429: (ErrorCode.RATE_LIMITED, True),
            500: (ErrorCode.SERVER_ERROR, True),
            503: (ErrorCode.SERVER_ERROR, True),
            302: (ErrorCode.HTTP_ERROR, False),
        }
        for status, (expected_code, expected_retryable) in cases.items():
            with self.subTest(status=status):
                error = pms_errors.http_error(status, "remote message")
                self.assertEqual(error.code, expected_code)
                self.assertEqual(error.http_status, status)
                self.assertEqual(error.retryable, expected_retryable)
                self.assertIn("remote message", error.message)

    def test_timeout_network_errors_are_retryable(self) -> None:
        self.assertTrue(pms_errors.timeout_error(30).retryable)
        self.assertTrue(pms_errors.network_error("connection refused").retryable)
        self.assertEqual(pms_errors.timeout_error(30).code, ErrorCode.TIMEOUT)
        self.assertEqual(pms_errors.network_error("x").code, ErrorCode.NETWORK)

    def test_remote_error_details(self) -> None:
        error = pms_errors.remote_error({"code": 10500, "message": "参数缺失", "data": None})
        self.assertEqual(error.code, ErrorCode.REMOTE_ERROR)
        self.assertEqual(error.details["remoteCode"], 10500)
        self.assertIn("10500", error.message)


class ResponseNormalizeTest(unittest.TestCase):
    def test_code_message_data(self) -> None:
        envelope = normalize_envelope({"code": 0, "message": "ok", "data": {"a": 1}})
        self.assertEqual(envelope, {"code": 0, "message": "ok", "data": {"a": 1}})

    def test_numeric_string_code(self) -> None:
        envelope = normalize_envelope({"code": "200", "msg": "success", "data": []})
        self.assertEqual(envelope["code"], 200)
        self.assertEqual(envelope["message"], "success")

    def test_data_only(self) -> None:
        self.assertEqual(normalize_envelope({"data": [1, 2]})["data"], [1, 2])

    def test_direct_list(self) -> None:
        self.assertEqual(normalize_envelope([1, 2, 3]), {"code": 0, "message": "ok", "data": [1, 2, 3]})

    def test_direct_object(self) -> None:
        self.assertEqual(normalize_envelope({"assetId": "A"})["data"], {"assetId": "A"})

    def test_success_false(self) -> None:
        envelope = normalize_envelope({"success": False, "message": "失败"})
        self.assertNotEqual(envelope["code"], 0)

    def test_empty_payload(self) -> None:
        self.assertEqual(normalize_envelope(None), {"code": 0, "message": "ok", "data": None})

    def test_extract_list_variants(self) -> None:
        self.assertEqual(extract_list({"code": 0, "message": "ok", "data": {"list": [1, 2]}}), [1, 2])
        self.assertEqual(extract_list({"code": 0, "data": {"records": [3]}}), [3])
        self.assertEqual(extract_list({"code": 0, "data": [4, 5]}), [4, 5])
        self.assertEqual(extract_list([6]), [6])
        self.assertEqual(extract_list({"code": 0, "data": {"data": {"rows": [7]}}}), [7])
        self.assertEqual(extract_list({"code": 0, "data": None}), [])
        self.assertEqual(extract_list({"code": 0, "data": {"total": 3}}), [])

    def test_extract_total_variants(self) -> None:
        self.assertEqual(extract_total({"data": {"total": 5}}), 5)
        self.assertEqual(extract_total({"data": {"totalCount": "7"}}), 7)
        self.assertEqual(extract_total({"data": {"count": 2}}), 2)
        self.assertIsNone(extract_total({"data": {"list": []}}))
        self.assertIsNone(extract_total({"data": [1]}))

    def test_substitute_path(self) -> None:
        self.assertEqual(
            substitute_path("/assetCenter/queryServices/{assetType}", {"assetType": "transformer"}),
            "/assetCenter/queryServices/transformer",
        )
        self.assertEqual(
            substitute_path("/a/{name}/b", {"name": "带 空格/斜杠"}),
            "/a/%E5%B8%A6%20%E7%A9%BA%E6%A0%BC%2F%E6%96%9C%E6%9D%A0/b",
        )
        with self.assertRaises(PmsError) as ctx:
            substitute_path("/assetCenter/queryServices/{assetType}", {})
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_PARAM)

    def test_encode_query(self) -> None:
        self.assertEqual(encode_query({"a": 1, "b": None}), "a=1")
        self.assertEqual(encode_query({"flag": True}), "flag=true")
        self.assertEqual(encode_query({"ids": [1, 2]}), "ids=1%2C2")
        self.assertEqual(encode_query(None), "")


class TransportTest(BaseTestCase):
    def test_get_request_url_and_query(self) -> None:
        opener = FakeOpener([FakeResponse({"code": 0, "data": {"assetName": "1号主变"}})])
        with mock.patch("urllib.request.urlopen", opener):
            resp = token_client().get_asset_by_id("AST-102-0001")
        self.assertEqual(resp["data"]["assetName"], "1号主变")
        request = opener.requests[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIn("https://gw.example.com/assetCenter/queryServices/getAstById", request.full_url)
        self.assertIn("assetId=AST-102-0001", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")

    def test_post_json_body(self) -> None:
        opener = FakeOpener([FakeResponse({"code": 0, "data": {"list": [], "total": 0}})])
        with mock.patch("urllib.request.urlopen", opener):
            token_client().list_psr_by_filters(voltageLevel="220kV", pageNo=2)
        request = opener.requests[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertIn("Content-Type", {key.title() for key in request.headers})
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body, {"voltageLevel": "220kV", "pageNo": 2})
        self.assertNotIn("?", request.full_url)

    def test_mixed_style_path_param_and_query(self) -> None:
        opener = FakeOpener([FakeResponse({"code": 0, "data": {"total": 0, "list": []}})])
        with mock.patch("urllib.request.urlopen", opener):
            token_client().list_asset_params("transformer", voltageLevel="220kV")
        request = opener.requests[0]
        self.assertIn("/assetCenter/queryServices/transformer", request.full_url)
        self.assertIn("voltageLevel=220kV", request.full_url)

    def test_retry_then_success(self) -> None:
        opener = FakeOpener([urllib.error.URLError("boom"), FakeResponse({"code": 0, "data": {"ok": True}})])
        with mock.patch("urllib.request.urlopen", opener):
            resp = token_client(retry=1).get_asset_by_id("A1")
        self.assertTrue(resp["data"]["ok"])
        self.assertEqual(len(opener.requests), 2)

    def test_no_retry_on_auth_error(self) -> None:
        error = urllib.error.HTTPError(
            "https://gw.example.com/x",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"message":"token expired"}'),
        )
        opener = FakeOpener([error])
        with mock.patch("urllib.request.urlopen", opener):
            with self.assertRaises(PmsError) as ctx:
                token_client(retry=3).get_asset_by_id("A1")
        self.assertEqual(ctx.exception.code, ErrorCode.AUTH_FAILED)
        self.assertEqual(len(opener.requests), 1)
        self.assertIn("token expired", ctx.exception.message)

    def test_retry_on_500(self) -> None:
        error = urllib.error.HTTPError(
            "https://gw.example.com/x", 500, "Server Error", {}, io.BytesIO(b"upstream boom")
        )
        opener = FakeOpener([error, FakeResponse({"code": 0, "data": {"ok": 1}})])
        with mock.patch("urllib.request.urlopen", opener):
            resp = token_client(retry=1).get_asset_by_id("A1")
        self.assertEqual(resp["data"]["ok"], 1)
        self.assertEqual(len(opener.requests), 2)

    def test_timeout_error(self) -> None:
        opener = FakeOpener([urllib.error.URLError(socket.timeout("timed out"))])
        with mock.patch("urllib.request.urlopen", opener):
            with self.assertRaises(PmsError) as ctx:
                token_client(retry=0).get_asset_by_id("A1")
        self.assertEqual(ctx.exception.code, ErrorCode.TIMEOUT)
        self.assertTrue(ctx.exception.retryable)

    def test_network_error(self) -> None:
        opener = FakeOpener([urllib.error.URLError(ConnectionRefusedError(10061, "refused"))])
        with mock.patch("urllib.request.urlopen", opener):
            with self.assertRaises(PmsError) as ctx:
                token_client(retry=0).get_asset_by_id("A1")
        self.assertEqual(ctx.exception.code, ErrorCode.NETWORK)

    def test_remote_business_error(self) -> None:
        opener = FakeOpener([FakeResponse({"code": 10500, "message": "参数不合法", "data": None})])
        with mock.patch("urllib.request.urlopen", opener):
            with self.assertRaises(PmsError) as ctx:
                token_client().get_asset_by_id("A1")
        self.assertEqual(ctx.exception.code, ErrorCode.REMOTE_ERROR)
        self.assertIn("参数不合法", ctx.exception.message)

    def test_parse_error(self) -> None:
        opener = FakeOpener([FakeResponse("<html>gateway error</html>")])
        with mock.patch("urllib.request.urlopen", opener):
            with self.assertRaises(PmsError) as ctx:
                token_client().get_asset_by_id("A1")
        self.assertEqual(ctx.exception.code, ErrorCode.PARSE_ERROR)

    def test_empty_body(self) -> None:
        opener = FakeOpener([FakeResponse(b"")])
        with mock.patch("urllib.request.urlopen", opener):
            resp = token_client().get_asset_by_id("A1")
        self.assertEqual(resp["code"], 0)
        self.assertIsNone(resp["data"])

    def test_missing_base_url(self) -> None:
        client = PmsClient(PmsConfig(auth_mode="none", spec_path=str(SPEC_PATH), retry=0, timeout=5))
        with self.assertRaises(PmsError) as ctx:
            client.call_tool("get_asset_by_id", {"assetId": "A1"})
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_CONFIGURED)

    def test_auth_missing_token_blocks_call(self) -> None:
        client = PmsClient(
            PmsConfig(
                base_url="https://gw.example.com",
                auth_mode="token",
                token="",
                spec_path=str(SPEC_PATH),
                retry=0,
                timeout=5,
            )
        )
        with self.assertRaises(PmsError) as ctx:
            client.call_tool("get_asset_by_id", {"assetId": "A1"})
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_CONFIGURED)
        self.assertIn("PMS_TOKEN", ctx.exception.message)

    def test_response_meta_added_for_real_mode(self) -> None:
        opener = FakeOpener([FakeResponse({"code": 0, "data": {"a": 1}})])
        with mock.patch("urllib.request.urlopen", opener):
            resp = token_client().get_asset_by_id("A1")
        self.assertEqual(resp["meta"]["authMode"], "token")
        self.assertEqual(resp["meta"]["tool"], "get_asset_by_id")


class AuthTest(unittest.TestCase):
    def test_factory_modes(self) -> None:
        self.assertIsInstance(create_auth_provider(make_config(auth_mode="mock")), MockAuthProvider)
        self.assertIsInstance(create_auth_provider(make_config(auth_mode="none")), NoneAuthProvider)
        self.assertIsInstance(
            create_auth_provider(make_config(auth_mode="token", token="t")), TokenAuthProvider
        )
        self.assertIsInstance(
            create_auth_provider(make_config(auth_mode="appkey", app_key="k", app_secret="s")),
            AppKeyAuthProvider,
        )

    def test_unknown_mode(self) -> None:
        with self.assertRaises(PmsError) as ctx:
            create_auth_provider(make_config(auth_mode="oauth2"))
        self.assertEqual(ctx.exception.code, ErrorCode.AUTH_MODE_INVALID)

    def test_mock_and_none_headers(self) -> None:
        mock_headers = MockAuthProvider(make_config()).build_headers("GET", "/x")
        self.assertIn("X-PMS-Mock", mock_headers)
        self.assertEqual(NoneAuthProvider(make_config()).build_headers("GET", "/x"), {})

    def test_token_headers(self) -> None:
        provider = TokenAuthProvider(make_config(auth_mode="token", token="abc"))
        self.assertEqual(provider.build_headers("GET", "/x"), {"Authorization": "Bearer abc"})

    def test_token_missing_credentials(self) -> None:
        provider = TokenAuthProvider(make_config(auth_mode="token", token=""))
        self.assertTrue(provider.problems())
        with self.assertRaises(PmsError) as ctx:
            provider.build_headers("GET", "/x")
        self.assertEqual(ctx.exception.code, ErrorCode.AUTH_MISSING_CREDENTIALS)

    def test_appkey_missing_credentials(self) -> None:
        provider = AppKeyAuthProvider(make_config(auth_mode="appkey"))
        with self.assertRaises(PmsError) as ctx:
            provider.build_headers("GET", "/x")
        self.assertEqual(ctx.exception.code, ErrorCode.AUTH_MISSING_CREDENTIALS)
        self.assertIn("PMS_APP_KEY", ctx.exception.message)

    def test_appkey_headers_signed(self) -> None:
        provider = AppKeyAuthProvider(make_config(auth_mode="appkey", app_key="k", app_secret="s"))
        self.assertEqual(provider.problems(), [])
        method = "POST"
        path = "/WMCenter/defect/inquireDefect"
        query = {"stationId": "STA-220-01", "pageNo": 1}
        body = json.dumps({"deviceId": "AST-102-0001"}, ensure_ascii=False).encode("utf-8")
        headers = provider.build_headers(method, path, query, body)
        # 4 个 X-PMS-* 头齐全，且不含旧实现的 TODO 分支
        self.assertEqual(
            set(headers),
            {"X-PMS-App-Key", "X-PMS-Timestamp", "X-PMS-Nonce", "X-PMS-Signature"},
        )
        self.assertEqual(len(headers), 4)
        self.assertEqual(headers["X-PMS-App-Key"], "k")
        self.assertRegex(headers["X-PMS-Timestamp"], r"^[0-9]{13}$")
        self.assertTrue(headers["X-PMS-Nonce"])
        signature = headers["X-PMS-Signature"]
        self.assertRegex(signature, r"^[0-9a-f]{64}$")
        # 用返回的 timestamp/nonce + 请求参数按 canonical 规范手工复算
        canonical = "\n".join(
            [
                "k",
                method,
                path,
                canonical_query(query),
                hashlib.sha256(body).hexdigest(),
                headers["X-PMS-Timestamp"],
                headers["X-PMS-Nonce"],
            ]
        )
        expected = hmac.new(b"s", canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        self.assertEqual(signature, expected)
        self.assertEqual(signature, expected.lower())

    def test_signature_function_returns_hmac(self) -> None:
        signature = build_appkey_signature("k", "s", "GET", "/x", {"a": 1}, None, "1", "n")
        # 64 位小写 hex
        self.assertRegex(signature, r"^[0-9a-f]{64}$")
        # 与手工 canonical 复算一致（空 body 取 sha256(b"")）
        canonical = "\n".join(
            ["k", "GET", "/x", "a=1", hashlib.sha256(b"").hexdigest(), "1", "n"]
        )
        expected = hmac.new(b"s", canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        self.assertEqual(signature, expected)
        # body / timestamp 变化 → 签名变化
        changed_body = build_appkey_signature(
            "k", "s", "GET", "/x", {"a": 1}, b'{"a": 1}', "1", "n"
        )
        changed_timestamp = build_appkey_signature(
            "k", "s", "GET", "/x", {"a": 1}, None, "2", "n"
        )
        self.assertNotEqual(signature, changed_body)
        self.assertNotEqual(signature, changed_timestamp)

    def test_no_hardcoded_secrets_in_auth_module(self) -> None:
        source = (SPEC_PATH.parent.parent / "skills" / "pms-gateway-mcp" / "scripts" / "pms_client" / "auth.py").read_text(
            encoding="utf-8"
        )
        for marker in ("app_secret = \"", "appSecret=\"", "secret = '", "appKey = \""):
            self.assertNotIn(marker, source)

    def test_describe_masks_secrets(self) -> None:
        provider = TokenAuthProvider(make_config(auth_mode="token", token="abcdefghijklmnop"))
        described = provider.describe()
        self.assertTrue(described["hasToken"])
        self.assertNotIn("abcdefghijklmnop", json.dumps(described, ensure_ascii=False))
        appkey_provider = AppKeyAuthProvider(make_config(auth_mode="appkey", app_key="key12345678", app_secret="s"))
        self.assertNotIn("key12345678", json.dumps(appkey_provider.describe(), ensure_ascii=False))

    def test_auth_provider_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            AuthProvider(make_config())  # type: ignore[abstract]


class ConfigTest(unittest.TestCase):
    def test_defaults_are_mock(self) -> None:
        config = PmsConfig.from_env({})
        self.assertEqual(config.auth_mode, "mock")
        self.assertTrue(config.is_mock)
        self.assertEqual(config.timeout, 30.0)
        self.assertEqual(config.retry, 1)
        self.assertEqual(config.validate(), [])

    def test_reads_all_env_vars(self) -> None:
        env = {
            "PMS_GATEWAY_BASE_URL": "https://gw.example.com",
            "PMS_AUTH_MODE": "APPKEY",
            "PMS_APP_KEY": "k",
            "PMS_APP_SECRET": "s",
            "PMS_TOKEN": "t",
            "PMS_TIMEOUT": "12.5",
            "PMS_RETRY": "3",
            "PMS_VERIFY_SSL": "0",
        }
        config = PmsConfig.from_env(env)
        self.assertEqual(config.base_url, "https://gw.example.com")
        self.assertEqual(config.auth_mode, "appkey")
        self.assertEqual(config.app_key, "k")
        self.assertEqual(config.app_secret, "s")
        self.assertEqual(config.token, "t")
        self.assertEqual(config.timeout, 12.5)
        self.assertEqual(config.retry, 3)
        self.assertFalse(config.verify_ssl)

    def test_explicit_args_override_env(self) -> None:
        config = PmsConfig.from_env({"PMS_AUTH_MODE": "mock"}, auth_mode="token", timeout=3, retry=0)
        self.assertEqual(config.auth_mode, "token")
        self.assertEqual(config.timeout, 3)
        self.assertEqual(config.retry, 0)

    def test_invalid_timeout(self) -> None:
        with self.assertRaises(PmsError) as ctx:
            PmsConfig.from_env({"PMS_TIMEOUT": "abc"})
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_CONFIGURED)

    def test_validate_token_mode(self) -> None:
        problems = PmsConfig.from_env(
            {"PMS_AUTH_MODE": "token", "PMS_GATEWAY_BASE_URL": "https://gw.example.com"}
        ).validate()
        self.assertTrue(any("PMS_TOKEN" in item for item in problems))

    def test_validate_appkey_mode(self) -> None:
        problems = PmsConfig.from_env(
            {"PMS_AUTH_MODE": "appkey", "PMS_GATEWAY_BASE_URL": "https://gw.example.com"}
        ).validate()
        self.assertTrue(any("PMS_APP_KEY" in item for item in problems))

    def test_validate_missing_base_url(self) -> None:
        problems = PmsConfig.from_env({"PMS_AUTH_MODE": "none"}).validate()
        self.assertTrue(any("PMS_GATEWAY_BASE_URL" in item for item in problems))

    def test_validate_bad_auth_mode(self) -> None:
        problems = PmsConfig.from_env({"PMS_AUTH_MODE": "oauth"}).validate()
        self.assertTrue(any("PMS_AUTH_MODE" in item for item in problems))

    def test_check_raises_on_problem(self) -> None:
        config = PmsConfig.from_env({"PMS_AUTH_MODE": "none"})
        with self.assertRaises(PmsError) as ctx:
            config.check()
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_CONFIGURED)

    def test_describe_has_no_secret_values(self) -> None:
        config = make_config(auth_mode="token", token="super-secret-token")
        described = json.dumps(config.describe(), ensure_ascii=False)
        self.assertNotIn("super-secret-token", described)
        self.assertIn("hasToken", described)

    def test_spec_path_resolution(self) -> None:
        path = find_spec_path(str(SPEC_PATH))
        self.assertEqual(path.resolve(), SPEC_PATH.resolve())
        self.assertEqual(find_spec_path(None).resolve(), SPEC_PATH.resolve())

    def test_env_spec_path_is_used(self) -> None:
        with mock.patch.dict("os.environ", {"PMS_SPEC_PATH": str(SPEC_PATH)}):
            self.assertEqual(find_spec_path().resolve(), SPEC_PATH.resolve())


if __name__ == "__main__":
    unittest.main()
