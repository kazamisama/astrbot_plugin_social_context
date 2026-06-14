"""状态持久化辅助方法（JSON 落盘 / 读取）。

无装饰器的纯逻辑，依赖主类提供的 self.state_path / self.groups / self.users /
self._last_save_time / self._cfg_bool / self._cfg_int / self._prune_stale_history。
_resolve_data_dir / _resolve_state_path 因涉及 __file__ 路径语义留在 main.py。
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import asdict
from typing import Any

from astrbot.api import logger

try:
    from ..models import GroupContext, MessageRecord, PokeRecord, UserContext
except ImportError:  # pragma: no cover - 兼容直接脚本方式导入
    from models import GroupContext, MessageRecord, PokeRecord, UserContext


class PersistenceMixin:
    """群/用户状态的 JSON 持久化辅助方法集合。"""

    def _save_if_needed(self, force: bool = False) -> None:
        if not self._cfg_bool("persist_enabled", True):
            return
        now = time.time()
        # v0.6.0+：写盘前先抛弃过期摘要，避免陈旧数据被持久化
        for group in self.groups.values():
            self._prune_stale_history(group, now)
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
                    messages=deque(MessageRecord(**{**m, "content": m.get("content", "")}) for m in item.get("messages", [])),
                    pokes=deque(PokeRecord(**p) for p in item.get("pokes", [])),
                    last_bot_reply_time=float(item.get("last_bot_reply_time", 0.0)),
                    last_injected_time=0.0,
                    total_messages_today=int(item.get("total_messages_today", 0)),
                    total_pokes_today=int(item.get("total_pokes_today", 0)),
                    autonomous_reply_count_today=int(item.get("autonomous_reply_count_today", 0)),
                    autonomous_reply_count_hour=int(item.get("autonomous_reply_count_hour", 0)),
                    autonomous_reply_hour=str(item.get("autonomous_reply_hour", "")),
                    last_judge_result=dict(item.get("last_judge_result", {})),
                    last_reset_date=str(item.get("last_reset_date", "")),
                    # v0.6.0+：历史摘要持久化
                    history_summary=str(item.get("history_summary", "") or ""),
                    history_summary_updated=float(item.get("history_summary_updated", 0.0) or 0.0),
                    history_daily_summary=str(item.get("history_daily_summary", "") or ""),
                    history_daily_updated=float(item.get("history_daily_updated", 0.0) or 0.0),
                )
                group.reset_daily_if_needed()
                # 载入时自动抛弃过期摘要（> 1 天）
                self._prune_stale_history(group, time.time())
                self.groups[str(gid)] = group
            for uid, item in raw.get("users", {}).items():
                user = UserContext(**item)
                user.reset_daily_if_needed()
                self.users[str(uid)] = user
        except Exception as exc:
            logger.warning(f"[social_context] 读取状态失败，已忽略旧状态: {exc}")

    def _group_to_json(self, group: GroupContext) -> dict[str, Any]:
        # 都不落盘：content 隐私自 v0.4.3 起；message_id 仅内存用；v0.5.3+ 主语指向字段同样仅内存
        return {
            "messages": [
                {k: v for k, v in asdict(m).items() if k not in (
                    "content",
                    "message_id",
                    "reply_to_sender_id",
                    "mentioned_user_ids",
                    "is_at_bot",
                    "is_at_all",
                )}
                for m in group.messages
            ],
            "pokes": [asdict(p) for p in group.pokes],
            "last_bot_reply_time": group.last_bot_reply_time,
            "last_injected_time": 0.0,
            "total_messages_today": group.total_messages_today,
            "total_pokes_today": group.total_pokes_today,
            "autonomous_reply_count_today": group.autonomous_reply_count_today,
            "autonomous_reply_count_hour": group.autonomous_reply_count_hour,
            "autonomous_reply_hour": group.autonomous_reply_hour,
            "last_judge_result": group.last_judge_result,
            "last_reset_date": group.last_reset_date,
            # v0.6.0+：历史摘要持久化（_prune_stale_history 会在 _save_if_needed 写盘前清理过期项）
            "history_summary": group.history_summary,
            "history_summary_updated": group.history_summary_updated,
            "history_daily_summary": group.history_daily_summary,
            "history_daily_updated": group.history_daily_updated,
        }
