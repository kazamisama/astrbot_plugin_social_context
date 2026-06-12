"""Prompt injection scanning helpers.

纯函数模块，不依赖 AstrBot，方便单元测试和复用。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

INJECTION_RISK_OPEN = "<INJECTION_RISK>"
INJECTION_RISK_CLOSE = "</INJECTION_RISK>"

# 用于扫描用户可控字符串（昵称、消息原文、戳一戳者 ID 等）。
# 命中片段会用 <INJECTION_RISK>…</INJECTION_RISK> 包裹，让判断模型
# 在做决策时视作不可信输入。
INJECTION_PATTERNS: tuple[str, ...] = (
    # 忽略 / 覆盖类指令
    r"忽略.{0,10}(指令|以上|之前|提示|全部|所有)",
    r"忘记.{0,6}(指令|提示|以上)",
    r"DO\s+NOT\s+(IGNORE|FORGET|OVERRIDE)",
    # 角色扮演类（长的在前，避免被短的截断）
    r"你是一个|你现在是|你现在[为]|你扮演|假装你[是为]",
    r"扮演.{0,8}(管理员|主人|系统|开发者)",
    # 对话角色伪装
    r"(system|assistant|user|tool)\s*:",
    r"<\|im_start\|>|<\|im_end\|>|>\{role\}<\|",
    # 注入分隔符
    r"---\s*BEGIN\s+(SYSTEM|REMINDER|HIDDEN)\s*---",
    r"---\s*END\s+(SYSTEM|REMINDER|HIDDEN)\s*---",
    r"\[(系统|管理员|主人|指令|override|override_instructions)\]",
    # 高优先级标签
    r"\b(IMPORTANT|CRITICAL|OVERRIDE|PRIORITY)\s*:",
)

_COMPILED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS)
_TAGGED_BLOCK_PATTERN = re.compile(r"(<INJECTION_RISK>.*?</INJECTION_RISK>)", re.DOTALL)


def scan_injection_risk(text: str | None) -> str:
    """扫描字符串中的潜在 prompt injection 片段并包裹。

    已经被 <INJECTION_RISK>…</INJECTION_RISK> 包住的片段会跳过，避免重复包裹。
    """
    if not text:
        return text or ""

    def _wrap(match: re.Match[str]) -> str:
        return f"{INJECTION_RISK_OPEN}{match.group(0)}{INJECTION_RISK_CLOSE}"

    scanned_parts: list[str] = []
    for part in _TAGGED_BLOCK_PATTERN.split(text):
        if part.startswith(INJECTION_RISK_OPEN) and part.endswith(INJECTION_RISK_CLOSE):
            scanned_parts.append(part)
            continue
        result = part
        for pattern in _COMPILED_PATTERNS:
            result = pattern.sub(_wrap, result)
        scanned_parts.append(result)
    return "".join(scanned_parts)


def scan_variables(
    variables: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
    enabled: bool = True,
) -> dict[str, Any]:
    """对指定 key 的字符串值做 prompt injection 扫描，返回新 dict。"""
    if not enabled:
        return dict(variables)
    scanned: dict[str, Any] = {}
    for key, value in variables.items():
        if key in keys and isinstance(value, str):
            scanned[key] = scan_injection_risk(value)
        else:
            scanned[key] = value
    return scanned
