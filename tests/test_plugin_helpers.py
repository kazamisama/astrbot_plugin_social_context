"""SocialContextPlugin 核心辅助行为回归测试。"""

from __future__ import annotations

import sys
import unittest
from collections import deque
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
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
    ) -> None:
        self.sender_name = sender_name
        self.sender_id = sender_id
        self.group_id = group_id
        self.unified_msg_origin = group_id
        self.message_str = message

    def get_sender_name(self) -> str:
        return self.sender_name

    def get_sender_id(self) -> str:
        return self.sender_id

    def get_group_id(self) -> str:
        return self.group_id


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
