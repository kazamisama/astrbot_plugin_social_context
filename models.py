"""Social Context 数据模型层。

无状态的 dataclass 与纯解析函数，从 main.py 抽出以减小主文件体量。
不依赖插件运行时状态（self），可被测试直接 import。
"""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class JudgeResult:
    """自主判断是否回复的结果。"""

    should_reply: bool = False
    confidence: float = 0.0
    reasoning: str = ""
    reply_style: str = "short"
    reply_intent: str = "join_topic"
    persona_id: str = ""


def _extract_json(text: str) -> dict[str, Any]:
    """从模型输出中稳健提取 JSON 对象。"""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        return json.loads(match.group())

    raise ValueError(f"无法从模型输出中提取 JSON: {text[:200]}")


def _clamp_01(value: Any) -> float:
    """钉位到 [0, 1]。"""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _to_bool(value: Any) -> bool:
    """宽松解析模型返回的布尔值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "是"}
    return bool(value)


@dataclass
class MessageRecord:
    """短期消息记录。"""

    sender_id: str
    sender_name: str
    content: str
    timestamp: float
    is_bot: bool = False
    # 仅在内存中使用（不持久化），用于按消息 id 在窗口中定位原消息。
    # 进程重启后会被 _load_state 默认为空字符串。
    message_id: str = ""
    # v0.5.3+：主语指向信号（均不持久化）
    # - reply_to_sender_id：这条消息是回复谁（来自 chain 的 Reply 组件，回溯到原消息 sender）
    # - mentioned_user_ids：@ 了哪些人（来自 chain 的 At 组件）
    # - is_at_bot：是否明确 @ 了 bot
    # - is_at_all：是否 @全体成员
    reply_to_sender_id: str = ""
    mentioned_user_ids: tuple[str, ...] = ()
    is_at_bot: bool = False
    is_at_all: bool = False


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
    autonomous_reply_count_today: int = 0
    autonomous_reply_count_hour: int = 0
    autonomous_reply_hour: str = ""
    last_judge_result: dict[str, Any] = field(default_factory=dict)
    last_reset_date: str = ""
    # v0.6.0+：历史压缩摘要
    # - tier2 摘要：180s ~ 30min 内的消息由 LLM 压缩而成，按 interval 增量更新
    # - tier3 摘要：30min ~ 24h 内的消息由 tier2 摘要再压缩而成，按更长 interval 更新
    # - 持久化：保存到 JSON；超过 1 天的摘要（updated + 86400 < now）自动抛弃
    history_summary: str = ""
    history_summary_updated: float = 0.0
    history_daily_summary: str = ""
    history_daily_updated: float = 0.0
    # v0.6.1+：压缩并发保护（同一群同时只能有 1 个压缩在跑；不持久化）
    history_compress_inflight: bool = False

    def reset_daily_if_needed(self) -> None:
        today = date.today().isoformat()
        if self.last_reset_date != today:
            self.last_reset_date = today
            self.total_messages_today = 0
            self.total_pokes_today = 0
            self.autonomous_reply_count_today = 0

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
    # v0.7.0+：群内身份（owner/admin/member），由群消息事件零成本更新
    role: str = "member"

    def reset_daily_if_needed(self) -> None:
        today = date.today().isoformat()
        if self.last_reset_date != today:
            self.last_reset_date = today
            self.message_count_today = 0
            self.poke_sent_today = 0
            self.poke_received_today = 0
