"""历史压缩 + 过期清理后台逻辑（tier2/tier3 + warn 去重）。

无装饰器的纯逻辑/后台循环，依赖主类提供的 config / context / groups /
_compress_tasks / _tier3_task / _stale_prune_task / _compress_warn_last /
_cfg_* / _get_messages_in_tier / _prune_stale_history / _scan_variables /
_save_if_needed。tier 边界辅助（_history_tier_bounds/_get_messages_in_tier/
_format_tier_label/_prune_stale_history）因被多处共用，留在 main.py。
"""

from __future__ import annotations

import asyncio
import time

from astrbot.api import logger


class CompressMixin:
    """历史压缩与过期清理的后台逻辑集合。"""

    HISTORY_COMPRESS_PROMPT = (
        "你是群聊历史上下文压缩助手。基于「旧摘要」和「新增消息」，"
        "输出一份更新后的简洁摘要，专门服务于「判断 bot 是否该插话」这一用途。\n"
        "必须保留的信息：\n"
        "- 群友在聊什么话题、谁和谁对话、bot 之前是否参与/承诺过什么\n"
        "- 是否有未完成的事 / 待回复的提问 / 失约的承诺\n"
        "- 群友关系变化（谁在跟谁互动、是否在 @ 谁）\n"
        "必须丢掉的信息：闲聊表情包、重复的客套、跟插话判断无关的细节。\n"
        "硬约束：输出不超过 {max_chars} 字，简洁到扫一眼就能看全。\n"
        "只输出更新后的摘要文本，不要 JSON，不要任何前缀说明。\n"
        "\n旧摘要：\n{old}\n"
        "\n新增消息（按时间顺序，已脱敏处理）：\n{new_messages}\n"
    )

    def _should_warn(self, key: str, throttle: float = 60.0) -> bool:
        """v0.6.2+：warning 去重门。同 key 在 throttle 秒内只允许 warn 一次。

        用于 LLM 失败 / provider 异常这类持续性错误，避免日志被刷爆。
        """
        now = time.time()
        last = self._compress_warn_last.get(key, 0.0)
        if (now - last) < throttle:
            return False
        self._compress_warn_last[key] = now
        # 顺手清理一下过期项（避免 dict 无限增长）
        if len(self._compress_warn_last) > 256:
            cutoff = now - throttle * 10
            self._compress_warn_last = {
                k: v for k, v in self._compress_warn_last.items() if v >= cutoff
            }
        return True

    @staticmethod
    def _log_compress_task_exception(task: asyncio.Task) -> None:
        """v0.6.2+：fire-and-forget task 异常回调。done_callback 用。

        不光 log 异常，还 try 把 inflight 标志清掉（如果 group 还在）。
        """
        try:
            exc = task.exception()
        except (asyncio.CancelledError, Exception):
            return
        if exc is None:
            return
        logger.warning(f"[social_context] 压缩 task 未捕获异常: {exc!r}")

    def _build_compress_prompt(self, old: str, new_messages: list, max_chars: int) -> str:
        """构造压缩 prompt。

        new_messages 已脱敏（content 可能为空，因为 v0.4.3 起不持久化正文）。
        压缩场景下，我们重新从当前 group 读出来时可以拿到 content。
        """
        if not new_messages:
            return ""
        lines: list[str] = []
        for m in new_messages:
            # 优先用 content（如果有），否则只显示时间 + sender
            content = (getattr(m, "content", "") or "").strip()
            sender_name = getattr(m, "sender_name", "") or getattr(m, "sender_id", "未知")
            if content:
                lines.append(f"- [{int(m.timestamp)}] {sender_name}: {content}")
            else:
                lines.append(f"- [{int(m.timestamp)}] {sender_name}: (无内容)")
        new_block = "\n".join(lines)
        # 旧摘要为空时提示是"首次压缩"
        old_block = old.strip() if old and old.strip() else "（暂无旧摘要，这是首次压缩）"
        return self.HISTORY_COMPRESS_PROMPT.format(
            max_chars=max_chars,
            old=old_block,
            new_messages=new_block,
        )

    async def _call_compress_llm(self, prompt: str, timeout: float) -> str | None:
        """调 judge_provider_id 对应的 provider 跑一次压缩。

        失败 / 超时 / 返回空 都返 None，调用方按"保留旧摘要"处理。
        v0.6.2+：warning 走 _should_warn 去重，避免 LLM 挂掉时日志被刷爆。
        """
        if not prompt:
            return None
        provider_id = str(self.config.get("judge_provider_id", "") or "").strip()
        if not provider_id:
            return None
        try:
            provider = self.context.get_provider_by_id(provider_id)
        except Exception as exc:
            if self._should_warn(f"get_provider:{provider_id}"):
                logger.warning(f"[social_context] 获取压缩 provider 失败: {exc}")
            return None
        if not provider:
            if self._should_warn(f"provider_none:{provider_id}"):
                logger.warning(f"[social_context] 压缩 provider 不存在: {provider_id}")
            return None
        try:
            response = await asyncio.wait_for(
                provider.text_chat(
                    prompt=prompt,
                    contexts=[],
                    image_urls=[],
                    system_prompt="",
                ),
                timeout=timeout,
            )
            content = (getattr(response, "completion_text", "") or "").strip()
            return content or None
        except asyncio.TimeoutError:
            if self._should_warn(f"timeout:{provider_id}"):
                logger.warning(f"[social_context] 历史压缩 LLM 超时（{timeout}s）")
            return None
        except Exception as exc:
            if self._should_warn(f"llm_error:{provider_id}:{type(exc).__name__}"):
                logger.warning(f"[social_context] 历史压缩 LLM 异常: {exc}")
            return None

    async def _compress_history_tier2(self, group_id: str) -> None:
        """tier2 压缩入口（fire-and-forget 调用方）。"""
        group = self.groups.get(group_id)
        if not group:
            return
        if group.history_compress_inflight:
            return
        if not self._cfg_bool("history_compress_tier2_enabled", True):
            return
        interval = self._cfg_int("history_compress_tier2_interval", 300, 1)
        max_chars = self._cfg_int("history_compress_tier2_max_chars", 200, 50)
        timeout = self._cfg_float("history_compress_timeout", 10.0, 1.0)
        now = time.time()
        if (now - group.history_summary_updated) < interval:
            return
        # 找 tier2 窗口里 > 上次更新时间 的消息
        msgs = self._get_messages_in_tier(
            group, now, 2, since_timestamp=group.history_summary_updated
        )
        # 还要算上"上次更新时间之后进入 tier1 但还没压过"的（防冷启动漏压）
        if not msgs:
            return
        group.history_compress_inflight = True
        try:
            # 先逐条扫一遍注入风险（scan_variables 针对单条 dict，列表需逐项扫）
            safe_msgs = [
                self._scan_variables(
                    {"ts": int(m.timestamp), "name": m.sender_name, "content": (m.content or "")[:200]},
                    keys=("name", "content"),
                )
                for m in msgs
            ]
            # 重新映射回 MessageRecord 形态（只用 ts/name/content，content 可能被截断/打标）
            class _LiteRec:
                __slots__ = ("timestamp", "sender_name", "content")
                def __init__(self, ts, name, content):
                    self.timestamp = ts
                    self.sender_name = name
                    self.content = content
            lite = [_LiteRec(d["ts"], d["name"], d["content"]) for d in safe_msgs]
            prompt = self._build_compress_prompt(
                group.history_summary, lite, max_chars
            )
            new_summary = await self._call_compress_llm(prompt, timeout)
            if new_summary:
                # 截断保护
                if len(new_summary) > max_chars * 2:
                    new_summary = new_summary[: max_chars * 2]
                group.history_summary = new_summary
                # 更新 updated 到本次新增消息里最新一条的时间戳
                group.history_summary_updated = max(m.timestamp for m in msgs)
            else:
                # 失败：不更新 updated，下次再试
                logger.debug("[social_context] tier2 压缩未拿到结果，保留旧摘要")
        finally:
            group.history_compress_inflight = False

    async def _compress_history_tier3(self, group_id: str) -> None:
        """tier3 压缩入口（定时器调用方）。输入是 tier2 摘要 + tier3 窗口内新消息。"""
        group = self.groups.get(group_id)
        if not group:
            return
        if group.history_compress_inflight:
            return
        if not self._cfg_bool("history_compress_tier3_enabled", True):
            return
        interval = self._cfg_int("history_compress_tier3_interval", 3600, 1)
        max_chars = self._cfg_int("history_compress_tier3_max_chars", 300, 50)
        timeout = self._cfg_float("history_compress_timeout", 10.0, 1.0)
        now = time.time()
        if (now - group.history_daily_updated) < interval:
            return
        # tier3 摘要的输入：tier2 当前摘要 + tier3 窗口里 > 上次更新时间 的消息
        msgs = self._get_messages_in_tier(
            group, now, 3, since_timestamp=group.history_daily_updated
        )
        if not msgs and not group.history_summary:
            return
        group.history_compress_inflight = True
        try:
            # tier3 的"旧摘要"是历史 tier3 摘要，参考信息加上 tier2 摘要作为"更新源"
            old_block = group.history_daily_summary or "（暂无 tier3 旧摘要）"
            if group.history_summary:
                old_block += f"\n\n近期补充（tier2 摘要）：\n{group.history_summary}"
            prompt = self.HISTORY_COMPRESS_PROMPT.format(
                max_chars=max_chars,
                old=old_block,
                new_messages=self._format_tier3_messages(msgs),
            )
            new_summary = await self._call_compress_llm(prompt, timeout)
            if new_summary:
                if len(new_summary) > max_chars * 2:
                    new_summary = new_summary[: max_chars * 2]
                group.history_daily_summary = new_summary
                group.history_daily_updated = now
            else:
                logger.debug("[social_context] tier3 压缩未拿到结果，保留旧摘要")
        finally:
            group.history_compress_inflight = False

    def _format_tier3_messages(self, msgs: list) -> str:
        """tier3 输入用：消息列表 → 简洁文本（带时间标签 + sender）。"""
        if not msgs:
            return "（无新增消息，仅基于旧摘要刷新）"
        lines: list[str] = []
        for m in msgs:
            content = (getattr(m, "content", "") or "").strip()
            sender = getattr(m, "sender_name", "") or getattr(m, "sender_id", "未知")
            # tier3 时段消息通常很多，每条只截前 60 字
            if content and len(content) > 60:
                content = content[:60] + "…"
            lines.append(f"- [{int(m.timestamp)}] {sender}: {content or '(无内容)'}")
        return "\n".join(lines)

    def _maybe_schedule_tier2_compress(self, group_id: str) -> None:
        """D 方案 tier2 触发点：on-message 后调用。fire-and-forget。

        v0.6.2+：done_callback 除了 discard 还挂一个异常记录器，
        避免 task 顶层抛异常时只看到「Task exception was never retrieved」。
        """
        if not self._cfg_bool("history_compress_tier2_enabled", True):
            return
        if not self._cfg_bool("history_compress_tier2_on_message", True):
            return
        # 简单节流：上次压缩在 interval 内就别发
        group = self.groups.get(group_id)
        if not group:
            return
        interval = self._cfg_int("history_compress_tier2_interval", 300, 1)
        if (time.time() - group.history_summary_updated) < interval:
            return
        if group.history_compress_inflight:
            return
        # fire-and-forget
        try:
            task = asyncio.create_task(self._compress_history_tier2(group_id))
            self._compress_tasks.add(task)
            # 一个 callback 处理 discard，另一个处理异常记录
            task.add_done_callback(self._compress_tasks.discard)
            task.add_done_callback(self._log_compress_task_exception)
        except RuntimeError:
            # 事件循环已关闭（插件 terminate 后还在跑），静默丢弃
            pass

    def _ensure_tier3_loop(self) -> None:
        """懒启动 tier3 后台循环。在 on_group_message 里调用。"""
        if self._tier3_task is not None and not self._tier3_task.done():
            return
        if not self._cfg_bool("history_compress_tier3_enabled", True):
            return
        try:
            self._tier3_task = asyncio.create_task(self._tier3_compress_loop())
        except RuntimeError:
            # 无事件循环或已关闭
            pass

    # ===== v0.6.3+：过期摘要定时清理（专治「静默群摘要僵在内存」）=====

    def _stale_prune_interval(self) -> int:
        """v0.6.3+：过期清理循环的执行间隔。

        - 默认 discard_age=86400 → 间隔 1h（clamp 到 3600）
        - 用户配 600（10min）→ 间隔 1min（clamp 下限 60）
        - 用户配 604800（一周）→ 间隔 1h（不会慢到 42h 才清）
        """
        discard = self._cfg_int("history_discard_age", 86400, 1)
        return max(60, min(discard // 4, 3600))

    async def _stale_history_prune_loop(self) -> None:
        """v0.6.3+：定时清理过期摘要 + force save。

        之前 `_prune_stale_history` 只在 load / save / 注入 prompt 前跑——
        完全静默的群，摘要过期后会一直留在内存和 JSON 里。
        这个循环兜底：每隔一段时间扫一次全群，把过期的清掉。
        """
        while True:
            try:
                interval = self._stale_prune_interval()
                await asyncio.sleep(interval)
                if not self._cfg_bool("persist_enabled", True):
                    continue
                now = time.time()
                pruned = 0
                for group in self.groups.values():
                    before_t2 = bool(group.history_summary)
                    before_t3 = bool(group.history_daily_summary)
                    self._prune_stale_history(group, now)
                    after_t2 = bool(group.history_summary)
                    after_t3 = bool(group.history_daily_summary)
                    if (before_t2, before_t3) != (after_t2, after_t3):
                        pruned += 1
                if pruned > 0:
                    # 内存清掉后立刻 force save，把清掉的结果同步到磁盘
                    self._save_if_needed(force=True)
                    # v0.6.4+：真清掉东西才 info 一次，避免每天 24 条日志噪音
                    if self._should_warn("stale_prune_acted"):
                        logger.info(
                            f"[social_context] 过期摘要清理: 本轮 {pruned} 个群受影响，已 force save"
                        )
            except asyncio.CancelledError:
                return
            except Exception as exc:
                if self._should_warn("stale_prune_loop"):
                    logger.warning(f"[social_context] 过期摘要清理循环异常: {exc}")
                await asyncio.sleep(60)
                continue

    def _ensure_stale_prune_loop(self) -> None:
        """懒启动过期清理循环。在 on_group_message 里调用。"""
        if self._stale_prune_task is not None and not self._stale_prune_task.done():
            return
        try:
            self._stale_prune_task = asyncio.create_task(self._stale_history_prune_loop())
        except RuntimeError:
            pass

    async def _tier3_compress_loop(self) -> None:
        """D 方案 tier3 循环：定时遍历所有群。

        v0.6.2+：外层加自愈 try/except，避免 await asyncio.sleep() 抛非 CancelledError
        时整个循环静默死亡。CancelledError 仍走外层正常退出（terminate 时触发）。
        """
        while True:
            try:
                while True:
                    interval = self._cfg_int("history_compress_tier3_interval", 3600, 60)
                    await asyncio.sleep(interval)
                    if not self._cfg_bool("history_compress_tier3_enabled", True):
                        continue
                    for gid in list(self.groups.keys()):
                        try:
                            await self._compress_history_tier3(gid)
                        except Exception as exc:
                            if self._should_warn(f"tier3_compress:{gid}"):
                                logger.warning(
                                    f"[social_context] tier3 压缩失败 [{gid}]: {exc}"
                                )
            except asyncio.CancelledError:
                # 插件 terminate 触发的正常取消，安静退出
                return
            except Exception as exc:
                # 自愈：非取消异常时记一笔后重进外层循环
                if self._should_warn("tier3_loop"):
                    logger.warning(f"[social_context] tier3 循环异常，将自愈重试: {exc}")
                await asyncio.sleep(60)  # 防忙等
                continue
