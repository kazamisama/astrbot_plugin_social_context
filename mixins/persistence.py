"""状态持久化辅助方法（JSON 落盘 / 读取）。

无装饰器的纯逻辑，依赖主类提供的 self.state_path / self.groups / self.users /
self._last_save_time / self._cfg_bool / self._cfg_int / self._prune_stale_history。
_resolve_data_dir / _resolve_state_path 因涉及 __file__ 路径语义留在 main.py。
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import asdict, fields
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
        interval = self._cfg_int("save_interval", 60, 1)
        if not force and now - self._last_save_time < interval:
            return
        self._last_save_time = now
        # 顺序不能反：整条淘汰要读摘要时间戳，先清摘要会把「2 天前还更新过摘要」
        # 的群误判成「从无活动」而整条删掉。
        self._prune_state(now)
        # 写盘前抛弃过期摘要，避免陈旧数据被持久化
        for group in self.groups.values():
            self._prune_stale_history(group, now)
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "groups": {gid: self._group_to_json(group) for gid, group in self.groups.items()},
                "users": {uid: asdict(user) for uid, user in self.users.items()},
            }
            self.state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"[social_context] 保存状态失败: {exc}")

    @staticmethod
    def _group_last_activity(group: GroupContext) -> float:
        """群状态的最后活动时间（消息 / 戳一戳 / 摘要 / bot 发言）。"""
        stamps = [
            group.last_bot_reply_time,
            group.last_injected_time,
            group.history_summary_updated,
            group.history_daily_updated,
        ]
        if group.messages:
            stamps.append(group.messages[-1].timestamp)
        if group.pokes:
            stamps.append(group.pokes[-1].timestamp)
        return max(stamps)

    def _prune_state(self, now: float) -> int:
        """淘汰长期无活动的群/用户状态，返回删除条目数。

        之前 self.users 没有任何出清路径：一个只在群里说过一句话的人会永久
        留在内存并每次全量写盘；self.groups 也只有 /social_context_reset 能删。
        """
        removed = 0

        group_ttl = self._cfg_int("state_group_ttl", 604800, 0)
        if group_ttl > 0:
            cutoff = now - group_ttl
            stale_groups = [
                gid
                for gid, group in self.groups.items()
                if self._group_last_activity(group) < cutoff
            ]
            for gid in stale_groups:
                del self.groups[gid]
                removed += 1

        user_ttl = self._cfg_int("state_user_ttl", 604800, 0)
        if user_ttl > 0:
            cutoff = now - user_ttl
            stale_users = [
                uid
                for uid, user in self.users.items()
                if max(user.last_message_time, user.last_poke_time) < cutoff
            ]
            for uid in stale_users:
                del self.users[uid]
                removed += 1

        max_users = self._cfg_int("state_user_max", 5000, 0)
        if max_users > 0 and len(self.users) > max_users:
            ordered = sorted(
                self.users.items(),
                key=lambda item: max(item[1].last_message_time, item[1].last_poke_time),
                reverse=True,
            )
            for uid, _user in ordered[max_users:]:
                del self.users[uid]
                removed += 1

        return removed

    def _load_state(self) -> None:
        if not self._cfg_bool("persist_enabled", True):
            return
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"[social_context] 状态文件读取失败，已忽略: {exc}")
            return
        if not isinstance(raw, dict):
            logger.warning("[social_context] 状态文件不是 JSON 对象，已忽略")
            return

        # 逐条载入：一条坏记录只丢它自己，不再让后面的条目一起消失。
        for gid, item in (raw.get("groups") or {}).items():
            try:
                self.groups[str(gid)] = self._group_from_json(item)
            except Exception as exc:
                logger.warning(f"[social_context] 跳过读不出的群状态 {gid}: {exc}")
        for uid, item in (raw.get("users") or {}).items():
            try:
                user = self._build_dataclass(UserContext, item)
                user.reset_daily_if_needed()
                self.users[str(uid)] = user
            except Exception as exc:
                logger.warning(f"[social_context] 跳过读不出的用户状态 {uid}: {exc}")

    @staticmethod
    def _build_dataclass(dataclass_type: type, item: Any, **defaults: Any) -> Any:
        """按 dataclass 字段过滤后构造；state 文件里的未知字段直接忽略。"""
        known = {field.name for field in fields(dataclass_type)}
        values = dict(defaults)
        values.update({key: value for key, value in item.items() if key in known})
        return dataclass_type(**values)

    def _group_from_json(self, item: Any) -> GroupContext:
        messages = deque(
            self._build_dataclass(MessageRecord, raw_message, content="")
            for raw_message in item.get("messages", [])
        )
        pokes = deque(
            self._build_dataclass(PokeRecord, raw_poke)
            for raw_poke in item.get("pokes", [])
        )
        group = GroupContext(
            messages=messages,
            pokes=pokes,
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
        # 载入时丢弃过期摘要（> 1 天）
        self._prune_stale_history(group, time.time())
        return group

    def _group_to_json(self, group: GroupContext) -> dict[str, Any]:
        # 都不落盘：content 隐私自 v0.4.3 起；message_id 仅内存用
        return {
            "messages": [
                {k: v for k, v in asdict(m).items() if k not in ("content", "message_id")}
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
