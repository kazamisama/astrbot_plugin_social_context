"""
AstrBot Social Context

轻量群聊状态感知层：
- 监听群聊消息与戳一戳 notice
- 维护短期群氛围、用户互动、bot 行为状态
- 在 LLM 请求前按需注入一段低噪声上下文

它借鉴 heartflow 的“原始群聊状态缓冲”思路，但不接管主动发言裁决，
定位为可复用的 social context layer。
"""

from __future__ import annotations

import json
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)


@dataclass
class MessageRecord:
    """短期消息记录。"""

    sender_id: str
    sender_name: str
    content: str
    timestamp: float
    is_bot: bool = False


@dataclass
class PokeRecord:
    """短期戳一戳记录。"""

    sender_id: str
    target_id: str
    timestamp: float


@dataclass
class GroupContext:
    """群聊短期状态。"""

    messages: deque[MessageRecord] = field(default_factory=deque)
    pokes: deque[PokeRecord] = field(default_factory=deque)
    last_bot_reply_time: float = 0.0
    last_injected_time: float = 0.0
    total_messages_today: int = 0
    total_pokes_today: int = 0
    last_reset_date: str = ""

    def reset_daily_if_needed(self) -> None:
        today = date.today().isoformat()
        if self.last_reset_date != today:
            self.last_reset_date = today
            self.total_messages_today = 0
            self.total_pokes_today = 0

    def prune(self, now: float, window: int, max_messages: int) -> None:
        cutoff = now - window
        while self.messages and self.messages[0].timestamp < cutoff:
            self.messages.popleft()
        while self.pokes and self.pokes[0].timestamp < cutoff:
            self.pokes.popleft()
        while len(self.messages) > max_messages:
            self.messages.popleft()


@dataclass
class UserContext:
    """用户互动状态。"""

    user_id: str
    message_count_today: int = 0
    poke_sent_today: int = 0
    poke_received_today: int = 0
    last_message_time: float = 0.0
    last_poke_time: float = 0.0
    familiarity: float = 0.0
    last_reset_date: str = ""

    def reset_daily_if_needed(self) -> None:
        today = date.today().isoformat()
        if self.last_reset_date != today:
            self.last_reset_date = today
            self.message_count_today = 0
            self.poke_sent_today = 0
            self.poke_received_today = 0


class SocialContextPlugin(Star):
    """群聊社会上下文插件。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.groups: dict[str, GroupContext] = {}
        self.users: dict[str, UserContext] = {}
        self._last_save_time = 0.0

        self.data_dir = self._resolve_data_dir()
        self.state_path = self._resolve_state_path()
        self._load_state()

    def _cfg_bool(self, key: str, default: bool) -> bool:
        return bool(self.config.get(key, default))

    def _cfg_int(self, key: str, default: int, min_value: int | None = None) -> int:
        try:
            value = int(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        if min_value is not None:
            value = max(min_value, value)
        return value

    def _cfg_float(self, key: str, default: float, min_value: float | None = None) -> float:
        try:
            value = float(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        if min_value is not None:
            value = max(min_value, value)
        return value

    def _resolve_data_dir(self) -> Path:
        base = Path("data") / "plugin_data" / "astrbot_plugin_social_context"
        try:
            base.mkdir(parents=True, exist_ok=True)
            return base
        except Exception:
            fallback = Path(__file__).parent / "data"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback

    def _resolve_state_path(self) -> Path:
        configured = str(self.config.get("state_path", "") or "").strip()
        if configured:
            return Path(configured)
        return self.data_dir / "social_context_state.json"

    def _get_group(self, group_id: str) -> GroupContext:
        group = self.groups.get(group_id)
        if group is None:
            group = GroupContext()
            group.reset_daily_if_needed()
            self.groups[group_id] = group
        group.reset_daily_if_needed()
        return group

    def _get_user(self, user_id: str) -> UserContext:
        user = self.users.get(user_id)
        if user is None:
            user = UserContext(user_id=user_id)
            user.reset_daily_if_needed()
            self.users[user_id] = user
        user.reset_daily_if_needed()
        return user

    def _scope_id(self, event: AstrMessageEvent) -> str:
        return event.get_group_id() or event.unified_msg_origin or "_private"

    def _sender_name(self, event: AstrMessageEvent) -> str:
        try:
            return event.get_sender_name() or str(event.get_sender_id())
        except Exception:
            return str(event.get_sender_id())

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        """监听群消息，维护短期状态窗口。"""
        if not self._cfg_bool("enabled", True):
            return

        group_id = event.get_group_id()
        if not group_id:
            return

        sender_id = str(event.get_sender_id())
        if not sender_id:
            return

        now = time.time()
        content = (event.message_str or "").strip()
        if not content:
            return

        group = self._get_group(group_id)
        user = self._get_user(sender_id)

        is_bot = sender_id == str(event.get_self_id())
        record = MessageRecord(
            sender_id=sender_id,
            sender_name=self._sender_name(event),
            content=content,
            timestamp=now,
            is_bot=is_bot,
        )
        group.messages.append(record)
        group.total_messages_today += 1
        if is_bot:
            group.last_bot_reply_time = now
        else:
            user.message_count_today += 1
            user.last_message_time = now
            user.familiarity = min(100.0, user.familiarity + self._cfg_float("familiarity_message_gain", 0.4, 0.0))

        group.prune(now, self._cfg_int("window_seconds", 60, 1), self._cfg_int("max_messages", 80, 1))
        self._save_if_needed()

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_group_poke(self, event: AstrMessageEvent):
        """监听 aiocqhttp 戳一戳 notice。"""
        if not self._cfg_bool("enabled", True):
            return
        if not isinstance(event, AiocqhttpMessageEvent):
            return

        raw = getattr(event, "message_obj", None)
        raw_message = getattr(raw, "raw_message", None)
        if not isinstance(raw_message, dict):
            return
        if raw_message.get("post_type") != "notice" or raw_message.get("notice_type") != "notify":
            return
        if raw_message.get("sub_type") != "poke":
            return

        group_id = str(raw_message.get("group_id") or event.get_group_id() or "")
        if not group_id:
            return

        sender_id = str(raw_message.get("user_id") or "")
        target_id = str(raw_message.get("target_id") or "")
        if not sender_id or not target_id:
            return

        now = time.time()
        group = self._get_group(group_id)
        group.pokes.append(PokeRecord(sender_id=sender_id, target_id=target_id, timestamp=now))
        group.total_pokes_today += 1

        sender = self._get_user(sender_id)
        target = self._get_user(target_id)
        sender.poke_sent_today += 1
        sender.last_poke_time = now
        sender.familiarity = min(100.0, sender.familiarity + self._cfg_float("familiarity_poke_gain", 0.8, 0.0))
        target.poke_received_today += 1
        target.last_poke_time = now

        group.prune(now, self._cfg_int("window_seconds", 60, 1), self._cfg_int("max_messages", 80, 1))
        self._save_if_needed(force=True)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, request):
        """在 LLM 请求前注入群聊状态摘要。"""
        if not self._cfg_bool("enabled", True):
            return
        if not self._reply_inject_enabled():
            return
        if not hasattr(request, "system_prompt"):
            return

        group_id = event.get_group_id()
        if not group_id and self._cfg_bool("only_group", True):
            return

        scope = self._scope_id(event)
        group = self._get_group(scope)
        now = time.time()
        inject_cd = self._cfg_float("inject_cd", 20.0, 0.0)
        if now - group.last_injected_time < inject_cd:
            return

        group.prune(now, self._cfg_int("window_seconds", 60, 1), self._cfg_int("max_messages", 80, 1))
        block = self.build_reply_prompt_block(scope, event)
        if not block:
            return

        group.last_injected_time = now
        request.system_prompt = (request.system_prompt or "").rstrip() + "\n\n" + block

    @filter.command("social_context")
    async def social_context_status(self, event: AstrMessageEvent):
        """查看当前会话的 social context 状态。"""
        scope = self._scope_id(event)
        group = self._get_group(scope)
        now = time.time()
        group.prune(now, self._cfg_int("window_seconds", 60, 1), self._cfg_int("max_messages", 80, 1))

        active_users = self._active_users(group)
        vibe = self._vibe_label(len(group.messages), len(active_users))
        since_bot = self._format_elapsed(now - group.last_bot_reply_time) if group.last_bot_reply_time else "暂无记录"

        text = (
            "🕵️ Social Context 状态\n\n"
            f"- 会话: {scope}\n"
            f"- 窗口: {self._cfg_int('window_seconds', 60, 1)} 秒\n"
            f"- 氛围: {vibe}\n"
            f"- 窗口消息: {len(group.messages)} 条\n"
            f"- 窗口戳一戳: {len(group.pokes)} 次\n"
            f"- 活跃用户: {len(active_users)} 人\n"
            f"- bot 上次发言: {since_bot}\n"
            f"- 今日消息: {group.total_messages_today} 条\n"
            f"- 今日戳一戳: {group.total_pokes_today} 次"
        )
        event.set_result(event.plain_result(text))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("social_context_reset")
    async def social_context_reset(self, event: AstrMessageEvent):
        """重置当前会话的 social context 状态。"""
        scope = self._scope_id(event)
        self.groups.pop(scope, None)
        self._save_if_needed(force=True)
        event.set_result(event.plain_result("✅ 当前会话的 Social Context 已重置"))

    def _reply_inject_enabled(self) -> bool:
        """正式回复模型注入开关。

        v0.1.0 使用 inject_enabled；v0.2.0 起改名为 reply_inject_enabled。
        为兼容旧配置，reply_inject_enabled 缺省时回退到 inject_enabled。
        """
        if "reply_inject_enabled" in self.config:
            return self._cfg_bool("reply_inject_enabled", True)
        return self._cfg_bool("inject_enabled", True)

    def build_reply_prompt_block(self, scope: str, event: AstrMessageEvent) -> str:
        """构造给正式回复模型看的低优先级观察块。

        目标：帮助模型“怎么自然地说”，不用于判断是否应该触发回复。
        """
        group = self._get_group(scope)
        now = time.time()
        active_users = self._active_users(group)
        message_count = len(group.messages)
        poke_count = len(group.pokes)

        if message_count == 0 and poke_count == 0:
            return ""

        vibe = self._vibe_label(message_count, len(active_users))
        recent_speakers = self._top_speakers(group, limit=3)
        latest_poke = group.pokes[-1] if group.pokes else None
        current_user = self._get_user(str(event.get_sender_id()))

        parts = [
            "[群聊状态观察 / 正式回复参考]",
            f"最近{self._cfg_int('window_seconds', 60, 1)}秒：{vibe}，{message_count}条消息，{len(active_users)}人参与。",
        ]
        if recent_speakers:
            parts.append("最近较活跃的人：" + "、".join(recent_speakers) + "。")
        if poke_count:
            parts.append(f"窗口内有{poke_count}次戳一戳。")
        if latest_poke:
            parts.append(f"最近一次戳一戳：{latest_poke.sender_id} 戳了 {latest_poke.target_id}。")
        if group.last_bot_reply_time:
            parts.append(f"你上次在这个群发言是{self._format_elapsed(now - group.last_bot_reply_time)}前。")
        if current_user.familiarity > 0:
            parts.append(f"当前发言者今日消息{current_user.message_count_today}条，熟悉度约{current_user.familiarity:.1f}/100。")

        parts.append("这些只是低优先级观察：自然使用，不要复述统计，不要因为看到观察就强行解释。")
        return "\n".join(parts)

    def build_judge_prompt_block(self, scope: str, event: AstrMessageEvent, max_age: int | None = None) -> str:
        """构造给判断模型看的决策参考块。

        目标：帮助 heartflow / proactive 之类的小模型判断“该不该回”。
        文字会更偏向 social / timing / willingness，而不是回复措辞。
        """
        group = self._get_group(scope)
        now = time.time()
        max_age = max_age or self._cfg_int("judge_context_max_age", 180, 1)
        cutoff = now - max_age
        messages = [m for m in group.messages if m.timestamp >= cutoff]
        pokes = [p for p in group.pokes if p.timestamp >= cutoff]

        if not messages and not pokes:
            return ""

        active_users = {m.sender_id for m in messages if not m.is_bot}
        vibe = self._vibe_label(len(messages), len(active_users))
        speaker_counter = Counter(m.sender_name or m.sender_id for m in messages if not m.is_bot)
        top_speakers = [name for name, _ in speaker_counter.most_common(3)]
        latest_poke = pokes[-1] if pokes else None
        current_user = self._get_user(str(event.get_sender_id()))

        parts = [
            "## Social Context 判断参考",
            f"- 最近{max_age}秒：{vibe}，{len(messages)}条消息，{len(active_users)}名活跃用户，{len(pokes)}次戳一戳。",
        ]
        if top_speakers:
            parts.append(f"- 最近较活跃的人：{'、'.join(top_speakers)}。")
        if latest_poke:
            parts.append(f"- 最近一次戳一戳：{latest_poke.sender_id} 戳了 {latest_poke.target_id}。")
        if group.last_bot_reply_time:
            parts.append(f"- bot 上次发言距今约{self._format_elapsed(now - group.last_bot_reply_time)}。")
        if current_user.familiarity > 0 or current_user.message_count_today > 0 or current_user.poke_sent_today > 0:
            parts.append(
                f"- 当前发言者今日消息{current_user.message_count_today}条，戳人{current_user.poke_sent_today}次，熟悉度约{current_user.familiarity:.1f}/100。"
            )
        parts.append("- 使用方式：只作为 social/timing/willingness 的参考；不要因为观察存在就强行判定应该回复。")
        return "\n".join(parts)

    def _build_context_block(self, scope: str, event: AstrMessageEvent) -> str:
        """兼容 v0.1.0 的旧内部方法名。"""
        return self.build_reply_prompt_block(scope, event)

    def _active_users(self, group: GroupContext) -> set[str]:
        return {m.sender_id for m in group.messages if not m.is_bot}

    def _top_speakers(self, group: GroupContext, limit: int) -> list[str]:
        counter = Counter(m.sender_name or m.sender_id for m in group.messages if not m.is_bot)
        return [name for name, _ in counter.most_common(limit)]

    def _vibe_label(self, message_count: int, active_user_count: int) -> str:
        active_threshold = self._cfg_int("active_message_threshold", 6, 1)
        quiet_threshold = self._cfg_int("quiet_message_threshold", 1, 0)
        if message_count >= active_threshold and active_user_count >= 2:
            return "群聊较活跃"
        if message_count <= quiet_threshold:
            return "群聊偏安静"
        return "群聊有零散交流"

    def _format_elapsed(self, seconds: float) -> str:
        seconds = max(0, int(seconds))
        if seconds < 60:
            return f"{seconds}秒"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}分钟"
        return f"{minutes // 60}小时"

    def _save_if_needed(self, force: bool = False) -> None:
        if not self._cfg_bool("persist_enabled", True):
            return
        now = time.time()
        interval = self._cfg_int("save_interval", 60, 1)
        if not force and now - self._last_save_time < interval:
            return
        self._last_save_time = now
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "groups": {gid: self._group_to_json(group) for gid, group in self.groups.items()},
                "users": {uid: asdict(user) for uid, user in self.users.items()},
            }
            self.state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"[social_context] 保存状态失败: {exc}")

    def _load_state(self) -> None:
        if not self._cfg_bool("persist_enabled", True):
            return
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            for gid, item in raw.get("groups", {}).items():
                group = GroupContext(
                    messages=deque(MessageRecord(**m) for m in item.get("messages", [])),
                    pokes=deque(PokeRecord(**p) for p in item.get("pokes", [])),
                    last_bot_reply_time=float(item.get("last_bot_reply_time", 0.0)),
                    last_injected_time=0.0,
                    total_messages_today=int(item.get("total_messages_today", 0)),
                    total_pokes_today=int(item.get("total_pokes_today", 0)),
                    last_reset_date=str(item.get("last_reset_date", "")),
                )
                group.reset_daily_if_needed()
                self.groups[str(gid)] = group
            for uid, item in raw.get("users", {}).items():
                user = UserContext(**item)
                user.reset_daily_if_needed()
                self.users[str(uid)] = user
        except Exception as exc:
            logger.warning(f"[social_context] 读取状态失败，已忽略旧状态: {exc}")

    def _group_to_json(self, group: GroupContext) -> dict[str, Any]:
        return {
            "messages": [asdict(m) for m in group.messages],
            "pokes": [asdict(p) for p in group.pokes],
            "last_bot_reply_time": group.last_bot_reply_time,
            "last_injected_time": 0.0,
            "total_messages_today": group.total_messages_today,
            "total_pokes_today": group.total_pokes_today,
            "last_reset_date": group.last_reset_date,
        }

    async def terminate(self):
        self._save_if_needed(force=True)
