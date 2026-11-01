"""在线钩子与命令面的集成测试。

这些钩子此前完全没有测试：on_group_poke / on_decorating_result /
on_after_message_sent / social_context* 命令 / get_group_members_info。
钩子内联了闸门（enabled、群白名单）和状态写入，单测辅助方法覆盖不到。
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace

# tests._fakes 负责把 astrbot / 插件根目录插进 sys.path，必须先导入它
from tests._fakes import _AiocqhttpEvent, _Event, _real_plugin  # noqa: E402

from astrbot.core.message.components import Plain  # noqa: E402
from main import GroupContext, MessageRecord  # noqa: E402


class _HookTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_path = Path(self._tmp.name) / "state.json"
        self.plugin = self._make()

    def _make(self, **overrides):
        return _real_plugin(self.state_path, **overrides)


class DataDirTests(_HookTestBase):
    def test_data_dir_is_under_plugin_data(self) -> None:
        data_dir = self.plugin.data_dir
        self.assertTrue(data_dir.is_dir())
        self.assertEqual(data_dir.name, "astrbot_plugin_social_context")
        self.assertEqual(data_dir.parent.name, "plugin_data")


class PokeHookTests(_HookTestBase):
    def _poke_event(self, **raw) -> _AiocqhttpEvent:
        payload = {
            "post_type": "notice",
            "notice_type": "notify",
            "sub_type": "poke",
            "group_id": 12345,
            "user_id": "10001",
            "target_id": "99999",
        }
        payload.update(raw)
        return _AiocqhttpEvent(group_id="group-1", raw_message=payload)

    def test_poke_writes_group_and_user_state(self) -> None:
        asyncio.run(self.plugin.on_group_poke(self._poke_event()))

        group = self.plugin.groups["group-1"]
        self.assertEqual(len(group.pokes), 1)
        self.assertEqual(group.pokes[0].sender_id, "10001")
        self.assertEqual(group.pokes[0].target_id, "99999")
        self.assertEqual(group.total_pokes_today, 1)

        self.assertEqual(self.plugin.users["10001"].poke_sent_today, 1)
        self.assertEqual(self.plugin.users["99999"].poke_received_today, 1)
        self.assertAlmostEqual(self.plugin.users["10001"].familiarity, 0.8)
        self.assertAlmostEqual(self.plugin.users["99999"].familiarity, 0.0)

    def test_non_poke_notice_ignored(self) -> None:
        asyncio.run(self.plugin.on_group_poke(self._poke_event(notice_type="group_increase")))
        self.assertEqual(self.plugin.groups, {})

    def test_plain_message_event_ignored(self) -> None:
        """非 aiocqhttp 事件类型直接返回，不写任何状态。"""
        event = _Event(group_id="group-1")
        asyncio.run(self.plugin.on_group_poke(event))
        self.assertEqual(self.plugin.groups, {})

    def test_poke_without_target_ignored(self) -> None:
        asyncio.run(self.plugin.on_group_poke(self._poke_event(target_id="")))
        self.assertEqual(self.plugin.groups, {})

    def test_disabled_plugin_ignores_poke(self) -> None:
        self.plugin = self._make(enabled=False)
        asyncio.run(self.plugin.on_group_poke(self._poke_event()))
        self.assertEqual(self.plugin.groups, {})

    def test_unlisted_group_ignores_poke(self) -> None:
        self.plugin = self._make(group_whitelist=["other-group"])
        asyncio.run(self.plugin.on_group_poke(self._poke_event()))
        self.assertEqual(self.plugin.groups, {})


class DecoratingResultTests(_HookTestBase):
    def _seed_group(self, interlopers: int) -> None:
        messages = deque(
            [
                MessageRecord(
                    sender_id="10001",
                    sender_name="alice",
                    content="原消息",
                    timestamp=time.time(),
                    message_id="msg-target",
                )
            ]
        )
        for index in range(interlopers):
            messages.append(
                MessageRecord(
                    sender_id=f"2000{index}",
                    sender_name=f"user{index}",
                    content=f"插嘴{index}",
                    timestamp=time.time(),
                    message_id=f"msg-{index}",
                )
            )
        self.plugin.groups["group-1"] = GroupContext(messages=messages)

    def _event(self, *, chain=None, message_id: str = "msg-target", **kwargs) -> _AiocqhttpEvent:
        event = _AiocqhttpEvent(
            group_id="group-1",
            message_id=message_id,
            **kwargs,
        )
        event.result = SimpleNamespace(chain=chain if chain is not None else [Plain("hi")])
        return event

    def test_inserts_reply_and_mention_when_threshold_met(self) -> None:
        self._seed_group(interlopers=3)
        event = self._event()

        asyncio.run(self.plugin.on_decorating_result(event))

        chain = event.result.chain
        self.assertEqual(len(chain), 4)  # Reply + At + 零宽 Plain + 原文
        self.assertEqual(getattr(chain[0], "id", None), "msg-target")
        self.assertEqual(str(getattr(chain[1], "qq", "")), "10001")

    def test_no_change_below_threshold(self) -> None:
        self._seed_group(interlopers=1)
        event = self._event()

        asyncio.run(self.plugin.on_decorating_result(event))

        self.assertEqual(len(event.result.chain), 1)

    def test_respects_reply_step_switch(self) -> None:
        self.plugin = self._make(reply_step_enabled=False)
        self._seed_group(interlopers=5)
        event = self._event()

        asyncio.run(self.plugin.on_decorating_result(event))

        self.assertEqual(len(event.result.chain), 1)

    def test_include_at_can_be_disabled(self) -> None:
        self.plugin = self._make(reply_step_include_at=False)
        self._seed_group(interlopers=3)
        event = self._event()

        asyncio.run(self.plugin.on_decorating_result(event))

        self.assertEqual(len(event.result.chain), 2)  # 只有 Reply
        self.assertEqual(getattr(event.result.chain[0], "id", None), "msg-target")

    def test_unsupported_platform_skipped(self) -> None:
        self._seed_group(interlopers=3)
        event = self._event(platform_name="dingtalk")

        asyncio.run(self.plugin.on_decorating_result(event))

        self.assertEqual(len(event.result.chain), 1)

    def test_missing_target_message_id_skipped(self) -> None:
        self._seed_group(interlopers=3)
        event = self._event(message_id="")

        asyncio.run(self.plugin.on_decorating_result(event))

        self.assertEqual(len(event.result.chain), 1)

    def test_no_result_skipped(self) -> None:
        self._seed_group(interlopers=3)
        event = _AiocqhttpEvent(group_id="group-1", message_id="msg-target")
        event.result = None

        asyncio.run(self.plugin.on_decorating_result(event))

        self.assertIsNone(event.result)


class AfterMessageSentTests(_HookTestBase):
    def _event(self, chain) -> _AiocqhttpEvent:
        event = _AiocqhttpEvent(group_id="group-1", message_id="m-bot-1")
        event.result = SimpleNamespace(chain=chain)
        return event

    def test_bot_reply_written_back_to_state(self) -> None:
        event = self._event([Plain("你好呀")])

        asyncio.run(self.plugin.on_after_message_sent(event))

        group = self.plugin.groups["group-1"]
        self.assertEqual(len(group.messages), 1)
        record = group.messages[0]
        self.assertEqual(record.sender_id, "99999")
        self.assertEqual(record.sender_name, "bot")
        self.assertEqual(record.content, "你好呀")
        self.assertTrue(record.is_bot)
        self.assertEqual(record.message_id, "m-bot-1")
        self.assertAlmostEqual(group.last_bot_reply_time, record.timestamp)
        self.assertEqual(group.total_messages_today, 1)

    def test_empty_result_ignored(self) -> None:
        event = self._event([Plain("")])

        asyncio.run(self.plugin.on_after_message_sent(event))

        self.assertEqual(self.plugin.groups, {})

    def test_unlisted_group_ignored(self) -> None:
        self.plugin = self._make(group_whitelist=["other-group"])
        event = self._event([Plain("你好呀")])

        asyncio.run(self.plugin.on_after_message_sent(event))

        self.assertEqual(self.plugin.groups, {})


class CommandSurfaceTests(_HookTestBase):
    def _event(self, message: str = "") -> _AiocqhttpEvent:
        return _AiocqhttpEvent(group_id="group-1", message=message)

    def test_status_command_reports_window(self) -> None:
        self.plugin.groups["group-1"] = GroupContext(
            messages=deque(
                [
                    MessageRecord(sender_id="10001", sender_name="alice", content="hi", timestamp=time.time()),
                ]
            ),
            total_messages_today=1,
        )
        event = self._event("social_context")

        asyncio.run(self.plugin.social_context_status(event))

        self.assertIn("Social Context 状态", event.result)
        self.assertIn("窗口消息: 1 条", event.result)
        self.assertIn("活跃用户: 1 人", event.result)

    def test_status_command_on_unlisted_group(self) -> None:
        self.plugin = self._make(group_whitelist=["other-group"])
        event = self._event("social_context")

        asyncio.run(self.plugin.social_context_status(event))

        self.assertEqual("当前会话未启用 social_context", event.result)

    def test_judge_last_without_record(self) -> None:
        event = self._event("social_context_judge_last")

        asyncio.run(self.plugin.social_context_judge_last(event))

        self.assertEqual("暂无自主判断记录", event.result)

    def test_judge_last_reports_record(self) -> None:
        self.plugin.groups["group-1"] = GroupContext(
            last_judge_result={
                "triggered": True,
                "should_reply": True,
                "confidence": 0.8,
                "reasoning": "有人问 bot",
                "reply_style": "short",
                "reply_intent": "answer",
            }
        )
        event = self._event("social_context_judge_last")

        asyncio.run(self.plugin.social_context_judge_last(event))

        self.assertIn("是否触发: True", event.result)
        self.assertIn("有人问 bot", event.result)

    def test_status_command_routes_judge_last(self) -> None:
        """social_context judge_last 与独立命令行为一致。"""
        self.plugin.groups["group-1"] = GroupContext(
            last_judge_result={"triggered": False, "should_reply": False}
        )
        event = self._event("social_context judge_last")

        asyncio.run(self.plugin.social_context_status(event))

        self.assertIn("最近一次自主判断", event.result)

    def test_reset_command_clears_group(self) -> None:
        self.plugin.groups["group-1"] = GroupContext(total_messages_today=5)
        event = self._event("social_context_reset")

        asyncio.run(self.plugin.social_context_reset(event))

        self.assertNotIn("group-1", self.plugin.groups)
        self.assertIn("已重置", event.result)

    def test_commands_disabled_by_master_switch(self) -> None:
        self.plugin = self._make(enabled=False)

        for command in (
            self.plugin.social_context_status,
            self.plugin.social_context_judge_last,
            self.plugin.social_context_reset,
        ):
            event = self._event("social_context")
            asyncio.run(command(event))
            self.assertIsNone(event.result)


class MemberToolTests(_HookTestBase):
    def _event(self, **kwargs) -> _AiocqhttpEvent:
        return _AiocqhttpEvent(group_id="group-1", **kwargs)

    def test_disabled_plugin_returns_error(self) -> None:
        self.plugin = self._make(enabled=False)
        payload = json.loads(asyncio.run(self.plugin.get_group_members_info(self._event(), "")))
        self.assertIn("已关闭", payload["error"])

    def test_non_group_event_returns_error(self) -> None:
        event = _AiocqhttpEvent(group_id="", umo="aiocqhttp:FriendMessage:10001")
        payload = json.loads(asyncio.run(self.plugin.get_group_members_info(event, "")))
        self.assertEqual("这不是群聊", payload["error"])

    def test_unlisted_group_returns_error(self) -> None:
        self.plugin = self._make(group_whitelist=["other-group"])
        payload = json.loads(asyncio.run(self.plugin.get_group_members_info(self._event(), "")))
        self.assertIn("未启用", payload["error"])

    def test_non_aiocqhttp_platform_returns_error(self) -> None:
        event = _Event(group_id="group-1")
        payload = json.loads(asyncio.run(self.plugin.get_group_members_info(event, "")))
        self.assertIn("仅支持QQ群聊", payload["error"])

    def test_self_hint_reads_event_sender_without_api(self) -> None:
        event = self._event(
            raw_message={"sender": {"user_id": 10001, "card": "群名片", "nickname": "QQ名", "role": "admin"}}
        )
        payload = json.loads(asyncio.run(self.plugin.get_group_members_info(event, "我")))
        self.assertEqual("event_sender", payload["source"])
        self.assertEqual("10001", payload["current_sender"]["user_id"])
        self.assertEqual("群名片", payload["current_sender"]["display_name"])

    def test_cache_hit_serves_members_without_api(self) -> None:
        self.plugin._member_cache["group-1"] = (
            time.time(),
            [{"user_id": "10001", "card": "alice", "nickname": "alice"}],
            False,
        )
        payload = json.loads(asyncio.run(self.plugin.get_group_members_info(self._event(), "ali")))
        self.assertEqual("cache", payload["source"])
        self.assertEqual(1, payload["member_count"])
        self.assertEqual("10001", payload["members"][0]["user_id"])


class StartupConfigWarningTests(_HookTestBase):
    """启动时的配置自检：只警告「不报错但什么都不做」的配置。"""

    def test_warns_when_whitelist_empty(self) -> None:
        plugin = self._make(group_whitelist=[])
        with self.assertLogs("astrbot", level="WARNING") as cm:
            plugin._log_startup_warnings()
        self.assertIn("group_whitelist 为空", "\n".join(cm.output))

    def test_warns_when_judge_provider_missing(self) -> None:
        plugin = self._make(
            group_whitelist=["group-1"], judge_enabled=True, judge_provider_id=""
        )
        with self.assertLogs("astrbot", level="WARNING") as cm:
            plugin._log_startup_warnings()
        self.assertIn("judge_provider_id 未配置", "\n".join(cm.output))

    def test_quiet_when_configured(self) -> None:
        plugin = self._make(
            group_whitelist=["group-1"], judge_enabled=True, judge_provider_id="provider-x"
        )
        with self.assertNoLogs("astrbot", level="WARNING"):
            plugin._log_startup_warnings()
