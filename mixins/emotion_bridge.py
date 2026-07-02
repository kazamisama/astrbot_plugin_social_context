"""v0.8.12+：social_context → emotion_state_machine 的可选桥接。

社交上下文插件（social_context）可以选择性地消费情绪状态机插件
（astrbot_plugin_emotion_state_machine）暴露的公共 API，把用户消息喂
给情绪引擎观察，并在 judge 模型 prompt 里注入情绪状态块。

v0.8.12 砍掉 self-reply signal（接入点 3）——相关职责 v0.8.12 起迁回
ESM 端（ESM v0.10.0+ 新增 ``apply_self_reply_signal(event)`` 接管）。
social_context 现在只负责"读"emotion，不负责"写"emotion。

剩下的两个接入点：
  1. observe_text — on_group_message 喂用户消息给 ESM
  2. _build_emotion_block — judge 通道拿 emotion 块（降级路径，字符串
     拼接用）；主路径已迁到 main.py 直接调 ESM.to_text_part 拿独立
     TextPart。

缺失 / 未注册 / 抛异常完全静默降级，确保 emotion 不可用时
social_context 主流程不受影响。

参考实现：astrbot_plugin_private_proactive_reply 的 _get_emotion_plugin。
"""

from __future__ import annotations

import logging

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
    """

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _get_emotion_plugin(self) -> object | None:
        """解析 emotion_state_machine star 实例；缺失/异常时返回 None。

        v0.8.12+：检查列表从 3 个方法（observe_text / build_prompt_block /
        apply_signal）简化到 1 个（observe_text）——接入点 3 砍了之后不再
        依赖 apply_signal 写入路径；接入点 2 主路径走 to_text_part（v0.10.0+），
        降级路径走 build_prompt_block（v0.8.0+ 兼容）。observe_text 仍
        是必需的——它驱动整个 emotion 数据流。
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
        if not hasattr(star_instance, "observe_text"):
            logger.debug(
                "[social_context] emotion_state_machine 实例缺少 observe_text，跳过桥接。"
            )
            return None
        return star_instance

    def _emotion_scope(self, event: object) -> str:
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
    # v0.8.12+ 主路径已迁到 main.py 直接调 ESM.to_text_part；
    # 本函数保留作降级路径（ESM v0.10.0 之前或 to_text_part 不可用时）。
    # ------------------------------------------------------------------

    def _build_emotion_block(self, scope: str, user_id: str) -> str:
        """降级路径：取 emotion prompt block；不可用/异常/非字符串时返回空串。

        v0.8.12 起只作降级用：主路径在 main.py:_judge_should_reply 直接调
        ESM.to_text_part 拿独立 TextPart，emotion block 与 social context
        9 块平级。本函数供 to_text_part 不可用时（ESM < v0.10.0）字符串
        拼接使用。

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
    # 接入点 3：bot 精力查询（_judge_should_reply 调用）
    # v0.8.14+：从 ESM 拉取 bot 当前精力值，供判断模型和硬门槛使用。
    # ------------------------------------------------------------------

    def _get_bot_energy(self, scope: str) -> float | None:
        """从 ESM 拉取 bot 当前精力；不可用/异常时返回 None。

        ESM.get_bot_energy 返回 [0.0, 1.0]，1.0=精力充沛，0.0=完全耗尽。
        scope 透传给 ESM 以支持 per-scope 精力桶（取决于 ESM 的
        energy_per_scope 配置）。
        """
        if not self._cfg_bool("judge_energy_gate_enabled", True) and not self._cfg_bool(
            "judge_energy_inject_enabled", True
        ):
            return None
        emo = self._get_emotion_plugin()
        if emo is None:
            return None
        try:
            getter = getattr(emo, "get_bot_energy", None)
            if getter is None:
                return None
            # get_bot_energy 是同步方法，不需要 await
            energy = float(getter(scope))
            return energy
        except Exception as exc:
            logger.debug(f"[social_context] get_bot_energy 失败: {exc}")
            return None


# Re-export the logger so ``from .emotion_bridge import logger`` keeps
# working for any external consumer that imported the symbol previously.
_logging = logging.getLogger(__name__)
