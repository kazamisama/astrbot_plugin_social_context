"""群成员查询辅助方法（v0.7.0 整合自「群成员查询」插件）。

仅包含无装饰器的辅助逻辑；带 @filter.llm_tool 的 get_group_members_info
留在 main.py。本 Mixin 依赖主类提供的 self._raw_message / self._cfg_int /
self._member_cache。
"""

from __future__ import annotations

import json
import time
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)


class MembersMixin:
    """群成员名册查询的辅助方法集合。"""

    # 触发"获取当前发信人"的关键字
    _SELF_HINTS = frozenset(
        {"self", "me", "myself", "i", "0", "我", "我自己", "自己", "本人", "在下"}
    )

    def _extract_current_sender(self, event: AstrMessageEvent) -> dict[str, Any] | None:
        """从消息事件零成本提取当前发信人（不调 API）。"""
        raw = self._raw_message(event)
        sender = raw.get("sender")
        if isinstance(sender, dict) and sender.get("user_id") is not None:
            uid = sender.get("user_id")
            return {
                "user_id": str(uid),
                "display_name": (
                    sender.get("card") or sender.get("nickname") or f"用户{uid}"
                ),
                "username": sender.get("nickname") or f"用户{uid}",
                "role": sender.get("role", "member"),
            }
        return None

    @staticmethod
    def _format_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for m in members:
            uid = m.get("user_id")
            if uid is None:
                continue
            out.append(
                {
                    "user_id": str(uid),
                    "display_name": m.get("card") or m.get("nickname") or f"用户{uid}",
                    "username": m.get("nickname") or f"用户{uid}",
                    "role": m.get("role", "member"),
                }
            )
        return out

    @staticmethod
    def _filter_members(members: list[dict[str, Any]], hint: str) -> list[dict[str, Any]]:
        h = (hint or "").strip().lower()
        if not h:
            return members
        return [
            m
            for m in members
            if h in (m.get("display_name") or "").lower()
            or h in (m.get("username") or "").lower()
            or h == (m.get("user_id") or "").lower()
        ]

    def _member_cache_get(self, group_id: str):
        ttl = self._cfg_int("member_cache_ttl", 30, 0)
        if ttl <= 0:
            return None
        hit = self._member_cache.get(group_id)
        if not hit:
            return None
        ts, members, truncated = hit
        if time.time() - ts > ttl:
            self._member_cache.pop(group_id, None)
            return None
        return members, truncated

    def _member_cache_set(self, group_id: str, members: list, truncated: bool) -> None:
        if self._cfg_int("member_cache_ttl", 30, 0) <= 0:
            return
        self._member_cache[group_id] = (time.time(), members, truncated)

    async def _fetch_group_members(
        self, event: AiocqhttpMessageEvent
    ) -> list[dict[str, Any]] | None:
        try:
            group_id = event.get_group_id()
            if not group_id:
                return None
            return await event.bot.api.call_action(
                "get_group_member_list", group_id=group_id
            )
        except Exception as exc:
            logger.error(
                f"[social_context] get_group_member_list 调用失败: {exc}",
                exc_info=True,
            )
            return None

    @staticmethod
    def _members_json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
