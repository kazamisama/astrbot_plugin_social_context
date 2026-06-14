"""v0.8.0+：social_context → emotion_state_machine 的可选桥接。

社交上下文插件（social_context）可以选择性地消费情绪状态机插件
（astrbot_plugin_emotion_state_machine）暴露的公共 API，把用户消息喂
给情绪引擎观察、在判断模型 prompt 里拼入情绪状态块，并在 bot 自己
回复后给情绪引擎打一个轻量正向 signal。

三个接入点都通过 lazy + defensive 模式调用，对 emotion 插件缺失 /
未注册 / 抛异常完全静默降级，确保 emotion 不可用时 social_context
主流程不受影响。

参考实现：astrbot_plugin_private_proactive_reply 的 _get_emotion_plugin。
"""

from __future__ import annotations

import time
from typing import Any

from astrbot.api import logger


# 与 emotion_state_machine 插件的 metadata.yaml 中 name 字段一致。
EMOTION_STAR_NAME = "astrbot_plugin_emotion_state_machine"


class EmotionBridgeMixin:
    """social_context ↔ emotion_state_machine 桥接 mixin。

    依赖主类提供：
    - self.context: Context（含 get_registered_star 接口）
    - self.config: AstrBotConfig
    - self._cfg_bool / self._cfg_float: 配置解析助手
    - self._scope_id(event): 本地 scope 计算（降级路径使用）

    主类需要在 __init__ 里初始化：
    - self._emotion_signal_last: dict[str, float]
        接入点 3 的节流表（scope -> 上次打 signal 的 timestamp）。
    """

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _get_emotion_plugin(self) -> Any | None:
        """解析 emotion_state_machine star 实例；缺失/异常时返回 None。

        三个接入点分别需要 observe_text / build_prompt_block /
        apply_signal，缺一个就把整桥降级（部分缺失也比半残更可预测）。
        """
        try:
            get_star = getattr(self.context, "get_registered_star", None)
            if get_star is None:
                return None
            star_instance = get_star(EMOTION_STAR_NAME)
        except Exception as exc:
            logger.debug(f"[social_context] emotion_state_machine 不可用: {exc}")
            return None
        if star_instance is None:
            return None
        for method_name in ("observe_text", "build_prompt_block", "apply_signal"):
            if not hasattr(star_instance, method_name):
                logger.debug(
                    f"[social_context] emotion_state_machine 实例缺少 {method_name}，跳过桥接。"
                )
                return None
        return star_instance

    def _emotion_scope(self, event: Any) -> str:
        """计算与 emotion 插件对齐的 scope。

        优先用 emotion 自己的 get_scope(event) 以保证绝对一致（emotion
        内部已经做了 group_id → unified_msg_origin → _private 降级）。
        降级到本地 _scope_id(event)，保证 emotion 插件不可用时
        social_context 自己的 scope 计算不受影响。
        """
        emo = self._get_emotion_plugin()
        if emo is not None:
            try:
                getter = getattr(emo, "get_scope", None)
                if getter is not None:
                    return str(getter(event))
            except Exception:
                pass
        return self._scope_id(event)

    # ------------------------------------------------------------------
    # 接入点 1：观察消息（on_group_message 调用）
    # ------------------------------------------------------------------

    def _feed_emotion_observation(
        self,
        scope: str,
        text: str,
        user_id: str,
        mentioned: bool,
    ) -> None:
        """把用户消息喂给 emotion 引擎观察。

        由 on_group_message 在写入消息记录后调用：
        - bot 自己的消息不喂（避免自反馈循环，由调用方跳过）
        - emotion 插件缺失/抛异常时静默跳过
        """
        if not self._cfg_bool("emotion_observe_enabled", True):
            return
        if not text:
            return
        emo = self._get_emotion_plugin()
        if emo is None:
            return
        try:
            emo.observe_text(
                scope=scope,
                text=text,
                user_id=user_id,
                mentioned=mentioned,
            )
        except Exception as exc:
            logger.debug(f"[social_context] emotion observe_text 失败: {exc}")

    # ------------------------------------------------------------------
    # 接入点 2：拼入判断模型 prompt（_judge_should_reply 调用）
    # ------------------------------------------------------------------

    def _build_emotion_block(self, scope: str, user_id: str) -> str:
        """取 emotion prompt block；不可用/异常/非字符串时返回空串。

        返回的字符串已 strip，由调用方拼到 context_block 后面。
        """
        if not self._cfg_bool("emotion_judge_inject_enabled", True):
            return ""
        emo = self._get_emotion_plugin()
        if emo is None:
            return ""
        try:
            block = emo.build_prompt_block(scope=scope, user_id=user_id)
        except Exception as exc:
            logger.debug(f"[social_context] emotion build_prompt_block 失败: {exc}")
            return ""
        if not isinstance(block, str):
            return ""
        return block.strip()

    # ------------------------------------------------------------------
    # 接入点 3：bot 主动回复后打轻量 signal（on_decorating_result 调用）
    # ------------------------------------------------------------------

    def _apply_emotion_self_reply_signal(self, scope: str, user_id: str) -> None:
        """bot 自己回复后向情绪引擎打一个轻量正向 signal。

        配置：
        - emotion_self_reply_signal_enabled (bool)
        - emotion_self_reply_signal (string, 默认 friendly)
        - emotion_self_reply_intensity (float, 默认 0.3)
        - emotion_self_reply_min_interval_seconds (float, 默认 30)
            用 self._emotion_signal_last[scope] 做 scope 维度节流，
            避免每条 bot 回复都打一次。

        降级：emotion 不可用 / signal 非法 / 抛异常都静默跳过。
        """
        if not self._cfg_bool("emotion_self_reply_signal_enabled", True):
            return
        signal = str(self.config.get("emotion_self_reply_signal", "friendly") or "friendly").strip()
        if not signal:
            return
        intensity = self._cfg_float("emotion_self_reply_intensity", 0.3, 0.0)
        min_interval = self._cfg_float("emotion_self_reply_min_interval_seconds", 30.0, 0.0)

        # 先确认 emotion 可用：缺失/异常时直接返回，不消耗节流时间戳，
        # 避免插件暂时下线后被自身节流锁住。
        emo = self._get_emotion_plugin()
        if emo is None:
            return

        if min_interval > 0:
            now = time.time()
            last = self._emotion_signal_last.get(scope, 0.0)
            if now - last < min_interval:
                return
            self._emotion_signal_last[scope] = now

        try:
            emo.apply_signal(
                scope=scope,
                user_id=user_id,
                signal=signal,
                intensity=intensity,
                reason="social_context_self_reply",
            )
        except Exception as exc:
            logger.debug(f"[social_context] emotion apply_signal 失败: {exc}")
