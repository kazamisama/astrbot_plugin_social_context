"""智能引用 output step。

逻辑：bot 准备回复的原消息（event.message_obj.message_id）之后
被插进了 N 条新消息（N >= threshold），就在 result.chain 头部
插入 Reply(id=原消息id) 组件，可选再加 At 组件提醒原消息发送者。

复用主插件的 `GroupContext.messages`（短期窗口内的 MessageRecord）
查找原消息位置，不维护独立队列。窗口外的消息自然不算入"被插嘴数"，
形成上限。

本模块完全独立（duck typing），不依赖主插件的 MessageRecord 类型，
方便单元测试。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from astrbot.core.message.components import At, Face, Image, Plain, Reply

# 不支持智能引用的平台（与 outputpro 保持一致）。
UNSUPPORTED_PLATFORMS: frozenset[str] = frozenset({"dingtalk"})

# chain 白名单：只有这些组件类型才会触发智能引用。
# 避免在 chain 含 Video / Forward / Nodes 等长组件时插入 Reply。
_REPLY_CHAIN_WHITELIST: tuple[type, ...] = (Plain, Image, Face, At)


class HasMessageId(Protocol):
    """duck-typed interface for messages with a stable id."""

    message_id: str


def find_interruption_count(
    messages: Sequence[HasMessageId],
    target_message_id: str,
) -> int | None:
    """在 messages 中找到 target_message_id 的位置，返回它之后被插了几条。

    返回 None 表示没找到（原消息不在窗口内或 target_message_id 为空）。
    """
    if not target_message_id:
        return None
    target = str(target_message_id)
    for idx, record in enumerate(messages):
        if getattr(record, "message_id", "") == target:
            return len(messages) - idx - 1
    return None


def should_insert_reply(
    chain: list,
    messages: Sequence[HasMessageId],
    target_message_id: str,
    threshold: int,
) -> tuple[bool, int]:
    """判断是否应在 chain 头部插入 Reply 组件。

    返回 (should_insert, pushed_count)。
    - threshold <= 0：直接关闭
    - chain 含非白名单组件（Video / Forward / Nodes 等）：跳过，pushed=0
    - target_message_id 不在 messages 中：跳过
    - pushed < threshold：跳过

    pushed_count 在未命中时仍返回计算结果（>=0），便于 debug。
    """
    if threshold <= 0:
        return False, 0
    if not all(isinstance(seg, _REPLY_CHAIN_WHITELIST) for seg in chain):
        return False, 0
    pushed = find_interruption_count(messages, target_message_id)
    if pushed is None or pushed < threshold:
        return False, pushed if pushed is not None else 0
    return True, pushed


# 对外暴露的辅助常量（供主插件 hook 直接 import 用）。
ReplyComponent = Reply
AtComponent = At
PlainComponent = Plain

__all__ = [
    "UNSUPPORTED_PLATFORMS",
    "find_interruption_count",
    "should_insert_reply",
    "ReplyComponent",
    "AtComponent",
    "PlainComponent",
]
