"""配置加载：环境变量 → :class:`PmsConfig`，以及 spec 文件定位。

环境变量（全部可选，默认 mock 模式，开箱可用）：

======================  ==================================================
PMS_GATEWAY_BASE_URL    中台网关完整地址，如 https://pms-gateway.example.com
PMS_AUTH_MODE           鉴权模式：mock / none / appkey / token，默认 mock
PMS_APP_KEY             appkey 模式的应用 key（向中台申请，禁止写进代码）
PMS_APP_SECRET          appkey 模式的应用密钥（向中台申请，禁止写进代码）
PMS_TOKEN               token 模式的访问令牌
PMS_TIMEOUT             单次请求超时秒数，默认 30
PMS_RETRY               失败重试次数（仅网络/5xx/429 等可重试错误），默认 1
PMS_SPEC_PATH           （扩展）显式指定 interfaces.json 路径
PMS_VERIFY_SSL          （扩展）是否校验证书，1/0，默认 1
======================  ==================================================
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ErrorCode, PmsError

# -- 环境变量名（文档与代码唯一引用点） -------------------------------------
ENV_BASE_URL = "PMS_GATEWAY_BASE_URL"
ENV_AUTH_MODE = "PMS_AUTH_MODE"
ENV_APP_KEY = "PMS_APP_KEY"
ENV_APP_SECRET = "PMS_APP_SECRET"
ENV_TOKEN = "PMS_TOKEN"
ENV_TIMEOUT = "PMS_TIMEOUT"
ENV_RETRY = "PMS_RETRY"
ENV_SPEC_PATH = "PMS_SPEC_PATH"
ENV_VERIFY_SSL = "PMS_VERIFY_SSL"

# -- 常量 -------------------------------------------------------------------
AUTH_MODES = ("mock", "none", "appkey", "token")
DEFAULT_AUTH_MODE = "mock"
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRY = 1
SPEC_FILENAME = "interfaces.json"
#: 相对技能根目录可能的 spec 位置（单一事实源仍在 expert-pack/spec/）
SPEC_SEARCH_SUBDIRS = (
    Path("spec") / SPEC_FILENAME,
    Path("references") / SPEC_FILENAME,
    Path(SPEC_FILENAME),
)


def _env(env: dict[str, str], name: str, default: str | None = None) -> str:
    value = env.get(name)
    if value is None or str(value).strip() == "":
        return default if default is not None else ""
    return str(value).strip()


def _as_float(raw: str, default: float, name: str) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise PmsError(
            ErrorCode.NOT_CONFIGURED,
            f"环境变量 {name}={raw!r} 不是合法数字，请改为秒数（如 30）",
        ) from None


def _as_int(raw: str, default: int, name: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise PmsError(
            ErrorCode.NOT_CONFIGURED,
            f"环境变量 {name}={raw!r} 不是合法整数，请改为次数（如 1）",
        ) from None


def _as_bool(raw: str, default: bool) -> bool:
    if raw == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def candidate_spec_paths(explicit: str | None = None) -> list[Path]:
    """列出 spec 文件候选路径（按优先级，已去重）。

    顺序：显式参数 → PMS_SPEC_PATH → 本文件向上逐级 → 当前工作目录向上逐级。
    ``pms_client`` 位于 ``expert-pack/skills/pms-gateway-mcp/scripts/``，
    向上三级即 ``expert-pack/``，因此默认安装结构下无需任何配置。
    """
    roots: list[Path] = [Path(__file__).resolve().parent, Path.cwd().resolve()]
    ordered: list[Path] = []

    def add(path: Path) -> None:
        resolved = path.expanduser()
        if resolved not in ordered:
            ordered.append(resolved)

    if explicit:
        add(Path(explicit))
    env_path = os.environ.get(ENV_SPEC_PATH, "").strip()
    if env_path:
        add(Path(env_path))

    for root in roots:
        cur = root
        for _ in range(10):
            for rel in SPEC_SEARCH_SUBDIRS:
                add(cur / rel)
            parent = cur.parent
            if parent == cur:
                break
            cur = parent
    return ordered


def find_spec_path(explicit: str | None = None) -> Path:
    """返回第一个存在的 spec 文件路径；找不到时抛出可操作错误。"""
    candidates = candidate_spec_paths(explicit)
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:  # pragma: no cover - 权限等极端情况
            continue
    tried = "\n".join(f"  - {p}" for p in candidates[:8])
    raise PmsError(
        ErrorCode.SPEC_NOT_FOUND,
        "未找到接口规格文件 interfaces.json。请任选一种方式修复：\n"
        "  1) 保持专家包目录结构（expert-pack/spec/interfaces.json 与 skills/ 同级）；\n"
        f"  2) 设置环境变量 {ENV_SPEC_PATH} 指向该文件绝对路径；\n"
        "  3) CLI 显式传 --spec <path>。\n"
        f"已查找位置：\n{tried}",
    )


@dataclass
class PmsConfig:
    """网关客户端配置。"""

    base_url: str = ""
    auth_mode: str = DEFAULT_AUTH_MODE
    app_key: str = ""
    app_secret: str = ""
    token: str = ""
    timeout: float = DEFAULT_TIMEOUT
    retry: int = DEFAULT_RETRY
    spec_path: str | None = None
    verify_ssl: bool = True

    # -- 构造 -----------------------------------------------------------
    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        *,
        base_url: str | None = None,
        auth_mode: str | None = None,
        timeout: float | None = None,
        retry: int | None = None,
        spec_path: str | None = None,
    ) -> "PmsConfig":
        """从环境变量构造配置，显式参数优先。"""
        source = dict(os.environ) if env is None else dict(env)
        timeout_raw = _env(source, ENV_TIMEOUT)
        retry_raw = _env(source, ENV_RETRY)
        mode = (auth_mode if auth_mode is not None else _env(source, ENV_AUTH_MODE, DEFAULT_AUTH_MODE)).lower()
        return cls(
            base_url=(base_url if base_url is not None else _env(source, ENV_BASE_URL)),
            auth_mode=mode,
            app_key=_env(source, ENV_APP_KEY),
            app_secret=_env(source, ENV_APP_SECRET),
            token=_env(source, ENV_TOKEN),
            timeout=(
                float(timeout)
                if timeout is not None
                else _as_float(timeout_raw, DEFAULT_TIMEOUT, ENV_TIMEOUT) if timeout_raw else DEFAULT_TIMEOUT
            ),
            retry=(
                int(retry)
                if retry is not None
                else _as_int(retry_raw, DEFAULT_RETRY, ENV_RETRY) if retry_raw else DEFAULT_RETRY
            ),
            spec_path=(spec_path if spec_path is not None else (_env(source, ENV_SPEC_PATH) or None)),
            verify_ssl=_as_bool(_env(source, ENV_VERIFY_SSL), True),
        )

    # -- 派生属性 -------------------------------------------------------
    @property
    def is_mock(self) -> bool:
        return self.auth_mode == "mock"

    def resolve_spec_path(self) -> Path:
        return find_spec_path(self.spec_path)

    # -- 校验与展示 -----------------------------------------------------
    def validate(self) -> list[str]:
        """返回配置问题清单（空列表=可正常调用）。"""
        problems: list[str] = []
        if self.auth_mode not in AUTH_MODES:
            problems.append(
                f"{ENV_AUTH_MODE}={self.auth_mode!r} 非法，可选值：{', '.join(AUTH_MODES)}（联调阶段请用 mock）"
            )
        if self.timeout <= 0:
            problems.append(f"{ENV_TIMEOUT} 必须大于 0 秒，当前 {self.timeout:g}")
        if self.retry < 0:
            problems.append(f"{ENV_RETRY} 不能为负数，当前 {self.retry}")

        if self.auth_mode == "mock":
            return problems
        if self.auth_mode == "appkey":
            missing = [name for name, value in ((ENV_APP_KEY, self.app_key), (ENV_APP_SECRET, self.app_secret)) if not value]
            if missing:
                problems.append(
                    f"appkey 模式缺少凭证：{'、'.join(missing)}。请向中台管理部门申请 appKey/appSecret，"
                    "并通过环境变量配置（禁止写进代码）；暂未申请到可先用 PMS_AUTH_MODE=mock 联调"
                )
        if self.auth_mode == "token" and not self.token:
            problems.append(
                f"token 模式缺少凭证：{ENV_TOKEN} 为空。请向中台申请访问令牌后通过环境变量配置；暂未申请到可先用 PMS_AUTH_MODE=mock 联调"
            )
        if not self.base_url:
            problems.append(
                f"{ENV_BASE_URL} 未配置，无法调用真实网关。请填写网关完整地址（如 https://pms-gateway.example.com）；"
                "仅联调时可设置 PMS_AUTH_MODE=mock 使用内置样例数据"
            )
        elif not str(self.base_url).lower().startswith(("http://", "https://")):
            problems.append(f"{ENV_BASE_URL}={self.base_url!r} 需以 http:// 或 https:// 开头")
        return problems

    def check(self) -> None:
        """配置不可用时抛出第一个问题（供调用前置检查）。"""
        problems = self.validate()
        if problems:
            raise PmsError(ErrorCode.NOT_CONFIGURED, problems[0], details={"problems": problems})

    def describe(self) -> dict[str, Any]:
        """脱敏后的配置快照（供 doctor / 日志）。"""
        return {
            "baseUrl": self.base_url or None,
            "authMode": self.auth_mode,
            "timeoutSeconds": self.timeout,
            "retryTimes": self.retry,
            "verifySsl": self.verify_ssl,
            "specPath": self.spec_path,
            "hasAppKey": bool(self.app_key),
            "hasAppSecret": bool(self.app_secret),
            "hasToken": bool(self.token),
        }
