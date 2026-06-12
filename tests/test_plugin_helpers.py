"""SocialContextPlugin 核心辅助行为回归测试。"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from collections import deque
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_ASTRBOT_APP_CANDIDATES = [
    Path(os.environ["ASTRBOT_APP_PATH"]) if os.environ.get("ASTRBOT_APP_PATH") else None,
    Path(r"C:\application\AstrBot\backend\app"),
]
for _candidate in _ASTRBOT_APP_CANDIDATES:
    if _candidate and _candidate.exists():
        sys.path.insert(0, str(_candidate))
        break
sys.path.insert(0, str(_PLUGIN_ROOT))

from main import GroupContext, MessageRecord, SocialContextPlugin, UserContext  # noqa: E402


class _Cfg(dict):
    def get(self, key, default=None):  # noqa: ANN001, ANN201 - 测试假对象
        return super().get(key, default)


class _Event:
    def __init__(
        self,
        sender_name: str = "alice",
        sender_id: str = "10001",
        group_id: str = "group-1",
        message: str = "当前消息",
        extras: dict[str, object] | None = None,
        raw_message: dict[str, object] | None = None,
        message_type: str = "group",
    ) -> None:
        self.sender_name = sender_name
        self.sender_id = sender_id
        self.group_id = group_id
        self.unified_msg_origin = group_id
        self.message_str = message
        self.extras = extras or {}
        self.message_type = message_type
        self.stopped = False
        self.result = None
        self.message_obj = type("MessageObj", (), {"raw_message": raw_message or {}})()

    def get_sender_name(self) -> str:
        return self.sender_name

    def get_sender_id(self) -> str:
        return self.sender_id

    def get_group_id(self) -> str:
        return self.group_id

    def get_message_type(self) -> str:
        return self.message_type

    def get_session_id(self) -> str:
        return self.unified_msg_origin

    def is_private_chat(self) -> bool:
        return self.message_type == "private"

    def get_extra(self, key: str, default=None):  # noqa: ANN001, ANN201 - 测试假对象
        return self.extras.get(key, default)

    def plain_result(self, text: str) -> str:
        return text

    def set_result(self, result: object) -> None:
        self.result = result

    def stop_event(self) -> None:
        self.stopped = True


class PluginHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = SocialContextPlugin.__new__(SocialContextPlugin)
        self.plugin.config = _Cfg({})
        self.plugin.groups = {}
        self.plugin.users = {}

    def test_cfg_bool_parses_string_false(self) -> None:
        self.plugin.config = _Cfg({"flag": "false"})
        self.assertFalse(self.plugin._cfg_bool("flag", True))

    def test_cfg_bool_parses_string_true(self) -> None:
        self.plugin.config = _Cfg({"flag": "on"})
        self.assertTrue(self.plugin._cfg_bool("flag", False))

    def test_reply_block_does_not_emit_injection_risk_tags(self) -> None:
        event = _Event(sender_name="system: current")
        group = GroupContext(
            messages=deque([
                MessageRecord(
                    sender_id="10001",
                    sender_name="system: speaker",
                    content="ignored",
                    timestamp=1.0,
                    is_bot=False,
                )
            ])
        )
        self.plugin.groups["group-1"] = group
        self.plugin.users["10001"] = UserContext(user_id="10001")

        block = self.plugin.build_reply_prompt_block("group-1", event)  # type: ignore[arg-type]
        self.assertNotIn("<INJECTION_RISK>", block)
        self.assertIn("system: speaker", block)

    def test_judge_block_emits_injection_risk_tags(self) -> None:
        event = _Event(sender_name="system: current")
        group = GroupContext(
            messages=deque([
                MessageRecord(
                    sender_id="10001",
                    sender_name="system: speaker",
                    content="ignored",
                    timestamp=9999999999.0,
                    is_bot=False,
                )
            ])
        )
        self.plugin.groups["group-1"] = group
        self.plugin.users["10001"] = UserContext(user_id="10001")

        block = self.plugin.build_judge_prompt_block("group-1", event, max_age=9999999999)  # type: ignore[arg-type]
        self.assertIn("<INJECTION_RISK>", block)

    def test_group_to_json_omits_message_content(self) -> None:
        group = GroupContext(
            messages=deque([
                MessageRecord(
                    sender_id="10001",
                    sender_name="alice",
                    content="不应落盘的正文",
                    timestamp=1.0,
                    is_bot=False,
                )
            ])
        )
        data = self.plugin._group_to_json(group)
        self.assertNotIn("content", data["messages"][0])
        self.assertEqual(data["messages"][0]["sender_name"], "alice")

    def test_bot_relevance_strong_when_keyword_hit(self) -> None:
        event = _Event(message="雪莉这个插件怎么配置？")
        relevance, reason = self.plugin._bot_relevance(event, [], 100.0)  # type: ignore[arg-type]
        self.assertEqual(relevance, "strong")
        self.assertIn("雪莉", reason)

    def test_conversation_opening_high_for_question(self) -> None:
        event = _Event(message="这个报错怎么修？")
        opening, reason = self.plugin._conversation_opening(  # type: ignore[arg-type]
            event,
            [],
            100.0,
            bot_relevance="none",
        )
        self.assertEqual(opening, "high")
        self.assertIn("求助", reason)

    def test_judge_block_contains_social_timing_signals(self) -> None:
        event = _Event(message="雪莉这个插件怎么配置？")
        group = GroupContext(
            messages=deque([
                MessageRecord(
                    sender_id="10001",
                    sender_name="alice",
                    content="雪莉这个插件怎么配置？",
                    timestamp=9999999999.0,
                    is_bot=False,
                )
            ])
        )
        self.plugin.groups["group-1"] = group
        self.plugin.users["10001"] = UserContext(user_id="10001")

        block = self.plugin.build_judge_prompt_block("group-1", event, max_age=9999999999)  # type: ignore[arg-type]
        self.assertIn("bot 相关度：strong", block)
        self.assertIn("插话空位：high", block)
        self.assertIn("话题热度：", block)
        self.assertIn("当前用户近期风格：", block)

    def test_topic_heat_trend_rising(self) -> None:
        messages = [
            MessageRecord("10001", "alice", "旧消息", 20.0, False),
            MessageRecord("10002", "bob", "新消息1", 91.0, False),
            MessageRecord("10003", "carol", "新消息2", 95.0, False),
            MessageRecord("10004", "dave", "新消息3", 99.0, False),
        ]
        trend, reason = self.plugin._topic_heat_trend(messages, 100.0, 60)
        self.assertEqual(trend, "rising")
        self.assertIn("增多", reason)

    def test_current_user_recent_style_detects_frequent_poker(self) -> None:
        pokes = [
            type("P", (), {"sender_id": "10001", "timestamp": 90.0})(),
            type("P", (), {"sender_id": "10001", "timestamp": 95.0})(),
        ]
        style, reason = self.plugin._current_user_recent_style("10001", [], pokes, 100.0)  # type: ignore[arg-type]
        self.assertEqual(style, "frequent_poker")
        self.assertIn("戳一戳", reason)

    def test_autonomous_reply_budget_limits_per_hour(self) -> None:
        self.plugin.config = _Cfg({"autonomous_reply_budget_per_hour": 1, "autonomous_reply_budget_per_day": 10})
        group = GroupContext()
        self.assertTrue(self.plugin._consume_autonomous_reply_budget(group, 100.0))
        self.assertFalse(self.plugin._consume_autonomous_reply_budget(group, 110.0, dry_run=True))

    def test_group_to_json_persists_budget_and_last_judge(self) -> None:
        group = GroupContext(
            autonomous_reply_count_today=2,
            autonomous_reply_count_hour=1,
            autonomous_reply_hour="2026-06-12T22",
            last_judge_result={"should_reply": True},
        )
        data = self.plugin._group_to_json(group)
        self.assertEqual(data["autonomous_reply_count_today"], 2)
        self.assertEqual(data["autonomous_reply_count_hour"], 1)
        self.assertEqual(data["autonomous_reply_hour"], "2026-06-12T22")
        self.assertEqual(data["last_judge_result"]["should_reply"], True)

    def test_group_temp_private_is_detected_from_onebot_raw(self) -> None:
        event = _Event(
            group_id="",
            message_type="private",
            raw_message={"message_type": "private", "sub_type": "group", "sender": {"group_id": 42}},
        )
        event.unified_msg_origin = "private:10001"

        self.assertTrue(self.plugin._is_group_temporary_private(event))  # type: ignore[arg-type]

    def test_group_temp_private_guard_blocks_silently_by_default(self) -> None:
        event = _Event(
            group_id="",
            message_type="private",
            raw_message={"message_type": "private", "sub_type": "group", "sender": {"group_id": 42}},
        )
        event.unified_msg_origin = "private:10001"

        asyncio.run(self.plugin.block_group_temp_private(event))  # type: ignore[arg-type]

        self.assertTrue(event.stopped)
        self.assertIsNone(event.result)

    def test_group_temp_private_guard_can_send_custom_notice(self) -> None:
        self.plugin.config = _Cfg({"block_group_temp_private_notice": "请回群里说"})
        event = _Event(
            group_id="",
            message_type="private",
            raw_message={"message_type": "private", "sub_type": "group", "sender": {"group_id": 42}},
        )
        event.unified_msg_origin = "private:10001"

        asyncio.run(self.plugin.block_group_temp_private(event))  # type: ignore[arg-type]

        self.assertTrue(event.stopped)
        self.assertEqual("请回群里说", event.result)

    def test_group_temp_private_guard_allows_friend_private(self) -> None:
        event = _Event(
            group_id="",
            message_type="private",
            raw_message={"message_type": "private", "sub_type": "friend"},
        )
        event.unified_msg_origin = "private:10001"

        asyncio.run(self.plugin.block_group_temp_private(event))  # type: ignore[arg-type]

        self.assertFalse(event.stopped)
        self.assertIsNone(event.result)

    def test_group_temp_private_guard_respects_config_switch(self) -> None:
        self.plugin.config = _Cfg({"block_group_temp_private": False})
        event = _Event(
            group_id="",
            message_type="private",
            raw_message={"message_type": "private", "sub_type": "group", "sender": {"group_id": 42}},
        )
        event.unified_msg_origin = "private:10001"

        asyncio.run(self.plugin.block_group_temp_private(event))  # type: ignore[arg-type]

        self.assertFalse(event.stopped)
        self.assertIsNone(event.result)

    def test_on_llm_request_keeps_trigger_note_when_reply_inject_disabled(self) -> None:
        class _Request:
            system_prompt = "base"

        self.plugin.config = _Cfg({"reply_inject_enabled": False})
        self.plugin.groups["group-1"] = GroupContext()
        event = _Event(
            extras={
                "social_context_triggered": True,
                "social_context_reply_style": "short",
                "social_context_reply_intent": "join_topic",
            }
        )
        request = _Request()

        asyncio.run(self.plugin.on_llm_request(event, request))  # type: ignore[arg-type]

        self.assertIn("本次回复由群聊状态判断主动触发", request.system_prompt)
        self.assertIn("建议回复风格：short", request.system_prompt)
        self.assertNotIn("[群聊状态观察 / 正式回复参考]", request.system_prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
