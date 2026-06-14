"""social_context → emotion_state_machine 桥接 Mixin 测试。

测试目标：EmotionBridgeMixin 的三个接入点（observe / build_prompt_block /
apply_signal）在以下场景下行为正确：
  - emotion 插件缺失（context.get_registered_star 返回 None）
  - emotion 插件缺失 get_registered_star 接口
  - emotion 插件缺少必需方法
  - emotion 插件方法抛异常
  - 关闭对应开关
  - bot 自己的消息不喂 emotion
  - 正常调用路径
  - scope 优先用 emotion.get_scope(event)
  - self_reply_signal 节流
  - 非法 signal 名静默忽略

参考 fake star 模式来自
astrbot_plugin_emotion_state_machine/tests/test_plugin_api.py。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

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

from main import SocialContextPlugin  # noqa: E402
from mixins.emotion_bridge import EMOTION_STAR_NAME  # noqa: E402


class _Cfg(dict):
    def get(self, key, default=None):  # noqa: ANN001, ANN201 - 测试假对象
        return super().get(key, default)


class _FakeEmotionStar:
    """Spy 形态的 emotion_state_machine star。

    每个方法用 SimpleNamespace 记录调用参数；可选 raise_on_* 模拟异常。
    支持 disabled_signals 集合（v0.3.0+ 新增 is_signal_enabled / try_apply_signal）。
    """

    def __init__(
        self,
        *,
        scope_for_event: str = "g-1",
        prompt_block: str = "## Bot Emotion State\nhappy",
        raise_on_observe: bool = False,
        raise_on_block: bool = False,
        raise_on_signal: bool = False,
        disabled_signals: tuple[str, ...] = (),
    ) -> None:
        self._scope_for_event = scope_for_event
        self._prompt_block = prompt_block
        self._raise_on_observe = raise_on_observe
        self._raise_on_block = raise_on_block
        self._raise_on_signal = raise_on_signal
        self._disabled_signals = {s.lower() for s in disabled_signals}
        self.observe_calls: list[dict] = []
        self.block_calls: list[dict] = []
        self.signal_calls: list[dict] = []
        self.try_signal_calls: list[dict] = []

    def get_scope(self, event: object) -> str:
        return self._scope_for_event

    def observe_text(self, *, scope, text, user_id, mentioned):  # noqa: ANN001
        self.observe_calls.append(
            {"scope": scope, "text": text, "user_id": user_id, "mentioned": mentioned}
        )
        if self._raise_on_observe:
            raise RuntimeError("emotion observe_text 故意失败")
        return SimpleNamespace(label="calm")

    def build_prompt_block(self, *, scope, user_id=""):  # noqa: ANN001
        self.block_calls.append({"scope": scope, "user_id": user_id})
        if self._raise_on_block:
            raise RuntimeError("emotion build_prompt_block 故意失败")
        return self._prompt_block

    def apply_signal(self, *, scope, user_id, signal, intensity, reason):  # noqa: ANN001
        self.signal_calls.append(
            {
                "scope": scope,
                "user_id": user_id,
                "signal": signal,
                "intensity": intensity,
                "reason": reason,
            }
        )
        if self._raise_on_signal:
            raise RuntimeError("emotion apply_signal 故意失败")
        return SimpleNamespace(label="calm")

    def try_apply_signal(self, *, scope, user_id, signal, intensity, reason):  # noqa: ANN001
        """v0.3.0+ 热路径安全变体：失败时返 None（被禁用 / 未知 signal /
        intensity 非法），不抛——ESM 自己捕获 ValueError/TypeError 并 warn。
        """
        self.try_signal_calls.append(
            {
                "scope": scope,
                "user_id": user_id,
                "signal": signal,
                "intensity": intensity,
                "reason": reason,
            }
        )
        if self._raise_on_signal:
            return None
        return SimpleNamespace(label="calm")

    def is_signal_enabled(self, signal: str) -> bool:
        return signal.lower() not in self._disabled_signals


def _make_plugin(config: dict | None = None) -> SocialContextPlugin:
    plugin = SocialContextPlugin.__new__(SocialContextPlugin)
    plugin.config = _Cfg(config or {})
    plugin.groups = {}
    plugin.users = {}
    plugin.context = SimpleNamespace()  # 默认：get_registered_star 缺失
    # __init__ 里需要的所有运行时字段
    plugin._emotion_signal_last = {}
    plugin._emotion_disabled_warn_last = {}
    return plugin


def _attach_emotion(plugin: SocialContextPlugin, star: _FakeEmotionStar) -> None:
    """把 fake star 挂到 plugin.context.get_registered_star。"""

    def _lookup(name: str):
        assert name == EMOTION_STAR_NAME
        return star

    plugin.context.get_registered_star = _lookup  # type: ignore[attr-defined]


class EmotionBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = _make_plugin()

    # ---- 缺失场景 ----

    def test_no_get_registered_star_attr_is_silent(self) -> None:
        # plugin.context 没有 get_registered_star
        self.plugin._feed_emotion_observation("g", "text", "u", False)
        self.assertEqual(self.plugin._build_emotion_block("g", "u"), "")
        self.plugin._apply_emotion_self_reply_signal("g", "u")
        # _emotion_signal_last 不应被写（信号没真打到，不应消耗节流时间戳）
        self.assertEqual(self.plugin._emotion_signal_last, {})

    def test_get_registered_star_returns_none_is_silent(self) -> None:
        self.plugin.context.get_registered_star = lambda _name: None  # type: ignore[attr-defined]
        self.plugin._feed_emotion_observation("g", "text", "u", False)
        self.assertEqual(self.plugin._build_emotion_block("g", "u"), "")
        self.plugin._apply_emotion_self_reply_signal("g", "u")
        self.assertEqual(self.plugin._emotion_signal_last, {})

    def test_get_registered_star_raises_is_silent(self) -> None:
        def _boom(_name):
            raise RuntimeError("registry hiccup")

        self.plugin.context.get_registered_star = _boom  # type: ignore[attr-defined]
        # 不应抛出
        self.plugin._feed_emotion_observation("g", "text", "u", False)
        self.assertEqual(self.plugin._build_emotion_block("g", "u"), "")
        self.plugin._apply_emotion_self_reply_signal("g", "u")

    def test_emotion_missing_method_is_silent(self) -> None:
        # 没有 apply_signal —— 视作不可用
        class _Partial(SimpleNamespace):
            def get_scope(self, event):
                return "g"

            def observe_text(self, **_):
                return None

            def build_prompt_block(self, **_):
                return "block"

        self.plugin.context.get_registered_star = lambda _name: _Partial()  # type: ignore[attr-defined]
        self.assertIsNone(self.plugin._get_emotion_plugin())
        # 走降级：build_emotion_block 应该返回空串
        self.assertEqual(self.plugin._build_emotion_block("g", "u"), "")

    # ---- 接入点 1：observe ----

    def test_observe_calls_emotion_with_args(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin._feed_emotion_observation("g-1", "hi bot", "u-1", mentioned=True)
        self.assertEqual(len(star.observe_calls), 1)
        call = star.observe_calls[0]
        self.assertEqual(call["scope"], "g-1")
        self.assertEqual(call["text"], "hi bot")
        self.assertEqual(call["user_id"], "u-1")
        self.assertTrue(call["mentioned"])

    def test_observe_observe_disabled_skips(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin.config["emotion_observe_enabled"] = False
        self.plugin._feed_emotion_observation("g-1", "hi", "u-1", False)
        self.assertEqual(star.observe_calls, [])

    def test_observe_empty_text_skips(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin._feed_emotion_observation("g-1", "", "u-1", False)
        self.assertEqual(star.observe_calls, [])

    def test_observe_raises_is_silent(self) -> None:
        star = _FakeEmotionStar(raise_on_observe=True)
        _attach_emotion(self.plugin, star)
        # 不应抛
        self.plugin._feed_emotion_observation("g-1", "hi", "u-1", False)

    # ---- 接入点 2：build_prompt_block ----

    def test_block_returns_stripped_text(self) -> None:
        star = _FakeEmotionStar(prompt_block="  ## Bot Emotion State\nhappy  \n")
        _attach_emotion(self.plugin, star)
        self.assertEqual(
            self.plugin._build_emotion_block("g-1", "u-1"),
            "## Bot Emotion State\nhappy",
        )

    def test_block_empty_when_disabled(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin.config["emotion_judge_inject_enabled"] = False
        self.assertEqual(self.plugin._build_emotion_block("g-1", "u-1"), "")
        self.assertEqual(star.block_calls, [])

    def test_block_empty_when_plugin_missing(self) -> None:
        self.assertEqual(self.plugin._build_emotion_block("g-1", "u-1"), "")

    def test_block_raises_returns_empty(self) -> None:
        star = _FakeEmotionStar(raise_on_block=True)
        _attach_emotion(self.plugin, star)
        self.assertEqual(self.plugin._build_emotion_block("g-1", "u-1"), "")

    def test_block_non_string_returns_empty(self) -> None:
        star = _FakeEmotionStar()
        # monkey-patch build_prompt_block 返非字符串
        star.build_prompt_block = lambda **_: 123  # type: ignore[assignment]
        _attach_emotion(self.plugin, star)
        self.assertEqual(self.plugin._build_emotion_block("g-1", "u-1"), "")

    # ---- v0.8.3：strip esm v0.3.0 HTML sentinel markers ----

    def test_block_strips_sentinels(self) -> None:
        """esm v0.3.0 wraps the block in `<!-- esm:emotion-block:start/end -->`.

        We must strip the markers before splicing into the judge prompt.
        """
        raw = (
            "<!-- esm:emotion-block:start -->\n"
            "## Bot Emotion State\nhappy\n"
            "<!-- esm:emotion-block:end -->"
        )
        star = _FakeEmotionStar(prompt_block=raw)
        _attach_emotion(self.plugin, star)
        block = self.plugin._build_emotion_block("g-1", "u-1")
        self.assertEqual(block, "## Bot Emotion State\nhappy")
        # No trace of the markers in the returned text.
        self.assertNotIn("esm:emotion-block", block)
        self.assertNotIn("<!--", block)
        self.assertNotIn("-->", block)

    def test_block_strips_sentinels_extra_whitespace(self) -> None:
        """Sentinels should still be stripped even if the upstream block
        uses unusual whitespace (extra blank lines, leading/trailing space).
        """
        raw = (
            "  <!-- esm:emotion-block:start -->\n\n"
            "  ## Bot Emotion State\nwarm\n\n"
            "  <!-- esm:emotion-block:end -->\n"
        )
        star = _FakeEmotionStar(prompt_block=raw)
        _attach_emotion(self.plugin, star)
        block = self.plugin._build_emotion_block("g-1", "u-1")
        self.assertEqual(block, "## Bot Emotion State\nwarm")

    def test_block_passes_through_when_no_sentinels(self) -> None:
        """If the upstream ever drops the markers (or returns plain text),
        we pass the block through unchanged. Defensive against format drift.
        """
        star = _FakeEmotionStar(prompt_block="## Bot Emotion State\nnaked")
        _attach_emotion(self.plugin, star)
        block = self.plugin._build_emotion_block("g-1", "u-1")
        self.assertEqual(block, "## Bot Emotion State\nnaked")

    # ---- 接入点 3：apply_signal ----

    def test_signal_calls_emotion_with_config(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        # v0.8.1+：调的是 try_apply_signal
        self.assertEqual(len(star.try_signal_calls), 1)
        call = star.try_signal_calls[0]
        self.assertEqual(call["scope"], "g-1")
        self.assertEqual(call["user_id"], "u-1")
        self.assertEqual(call["signal"], "friendly")
        self.assertAlmostEqual(call["intensity"], 0.3)
        self.assertEqual(call["reason"], "social_context_self_reply")

    def test_signal_uses_custom_signal_and_intensity(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin.config["emotion_self_reply_signal"] = "thanks"
        self.plugin.config["emotion_self_reply_intensity"] = 0.7
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        self.assertEqual(star.try_signal_calls[0]["signal"], "thanks")
        self.assertAlmostEqual(star.try_signal_calls[0]["intensity"], 0.7)

    def test_signal_disabled_skips(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin.config["emotion_self_reply_signal_enabled"] = False
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        self.assertEqual(star.signal_calls, [])
        # 节流表也不应被写
        self.assertEqual(self.plugin._emotion_signal_last, {})

    def test_signal_empty_signal_name_skips(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin.config["emotion_self_reply_signal"] = "   "
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        self.assertEqual(star.signal_calls, [])
        self.assertEqual(self.plugin._emotion_signal_last, {})

    def test_signal_throttled_by_min_interval(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin.config["emotion_self_reply_min_interval_seconds"] = 60.0
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        # 节流：30s 窗口内只打一次
        self.assertEqual(len(star.try_signal_calls), 1)
        # 节流表被写了
        self.assertIn("g-1", self.plugin._emotion_signal_last)

    def test_signal_throttle_is_per_scope(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin.config["emotion_self_reply_min_interval_seconds"] = 60.0
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        self.plugin._apply_emotion_self_reply_signal("g-2", "u-2")
        self.assertEqual(len(star.try_signal_calls), 2)

    def test_signal_throttle_zero_means_no_throttle(self) -> None:
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin.config["emotion_self_reply_min_interval_seconds"] = 0.0
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        self.assertEqual(len(star.try_signal_calls), 2)

    def test_signal_raises_is_silent(self) -> None:
        star = _FakeEmotionStar(raise_on_signal=True)
        _attach_emotion(self.plugin, star)
        # v0.8.1+：try_apply_signal 自己捕获并返 None，外层不应再抛
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        self.assertEqual(len(star.try_signal_calls), 1)

    def test_signal_throttle_does_not_consume_when_plugin_missing(self) -> None:
        # emotion 缺失时调一次，节流表不应被写（避免后续插件恢复后被节流锁住）
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        self.assertEqual(self.plugin._emotion_signal_last, {})

        # 之后挂上插件，立即能调到
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        # v0.8.1+：调的是 try_apply_signal
        self.assertEqual(len(star.try_signal_calls), 1)

    # ---- scope 路径 ----

    def test_emotion_scope_prefers_emotion_get_scope(self) -> None:
        star = _FakeEmotionStar(scope_for_event="from-emotion")
        _attach_emotion(self.plugin, star)
        event = SimpleNamespace()
        self.assertEqual(self.plugin._emotion_scope(event), "from-emotion")

    def test_emotion_scope_falls_back_to_local_when_plugin_missing(self) -> None:
        # 无 emotion 插件时，走主类 _scope_id 的 group_id → origin → _private 降级
        # 这里 _Event 没有 unified_msg_origin 属性，回退 _scope_id(event) 走 hasattr try/except
        # 用 SimpleNamespace 模拟没有 group_id 的私聊
        event = SimpleNamespace(
            get_group_id=lambda: "",
            unified_msg_origin="private:x",
        )
        # 没有 get_registered_star → 走本地降级
        self.assertEqual(self.plugin._emotion_scope(event), "private:x")

    def test_emotion_scope_falls_back_to_local_when_get_scope_raises(self) -> None:
        class _Boom(SimpleNamespace):
            def get_scope(self, _):
                raise RuntimeError("boom")

        self.plugin.context.get_registered_star = lambda _name: _Boom()  # type: ignore[attr-defined]
        event = SimpleNamespace(
            get_group_id=lambda: "g-7",
            unified_msg_origin="origin",
        )
        # _scope_id 本地版本优先 group_id
        self.assertEqual(self.plugin._emotion_scope(event), "g-7")

    # ---- MRO / 常量 ----

    def test_emotion_bridge_mixin_in_mro(self) -> None:
        from mixins.emotion_bridge import EmotionBridgeMixin
        self.assertIn(EmotionBridgeMixin, SocialContextPlugin.__mro__)

    def test_emotion_star_name_constant(self) -> None:
        self.assertEqual(EMOTION_STAR_NAME, "astrbot_plugin_emotion_state_machine")

    # ---- v0.8.1+：ESM v0.3.0 公共 API 适配 ----

    def test_signal_skipped_when_disabled_in_esm(self) -> None:
        """signal 在 ESM 的 disabled_signals 列表中：跳过打 signal，不调 try_apply_signal。"""
        star = _FakeEmotionStar(disabled_signals=("friendly",))
        _attach_emotion(self.plugin, star)
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        # 跳过：try_apply_signal / apply_signal 都没被调到
        self.assertEqual(star.try_signal_calls, [])
        self.assertEqual(star.signal_calls, [])
        # warn 去重表应被写
        self.assertIn("friendly", self.plugin._emotion_disabled_warn_last)

    def test_signal_disabled_warn_throttled_60s(self) -> None:
        """同 signal 60s 内只 warn 一次（避免刷屏）。"""
        star = _FakeEmotionStar(disabled_signals=("friendly",))
        _attach_emotion(self.plugin, star)
        # 第一次：warn
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        first_ts = self.plugin._emotion_disabled_warn_last["friendly"]
        # 第二次：30s 内，不应重写 warn 时间戳
        self.plugin._emotion_disabled_warn_last["friendly"] = first_ts + 5
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        # warn 时间戳仍是第一次 + 5（说明第二次没走 warn 分支）
        self.assertAlmostEqual(
            self.plugin._emotion_disabled_warn_last["friendly"], first_ts + 5
        )

    def test_signal_calls_try_apply_signal_not_apply_signal(self) -> None:
        """ESM 暴露 try_apply_signal 时优先调用它；apply_signal 不被直接调。"""
        star = _FakeEmotionStar()
        _attach_emotion(self.plugin, star)
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        self.assertEqual(len(star.try_signal_calls), 1)
        self.assertEqual(star.try_signal_calls[0]["signal"], "friendly")
        self.assertEqual(star.try_signal_calls[0]["reason"], "social_context_self_reply")
        # apply_signal 不被直接调
        self.assertEqual(star.signal_calls, [])

    def test_signal_falls_back_to_apply_signal_when_try_missing(self) -> None:
        """ESM 旧版（v0.2.x）没有 try_apply_signal 时降级到 apply_signal。

        用 class attr = None 模拟「该方法在实例上不存在」：bridge 的
        `getattr(emo, "try_apply_signal", None) or emo.apply_signal` 会
        拿到 None，落到 apply_signal；is_signal_enabled 同理被跳过。
        """
        class _OldESM(_FakeEmotionStar):
            try_apply_signal = None  # type: ignore[assignment]
            is_signal_enabled = None  # type: ignore[assignment]

        star = _OldESM()
        _attach_emotion(self.plugin, star)
        self.plugin._apply_emotion_self_reply_signal("g-1", "u-1")
        # 降级到 apply_signal：spy 记录到 signal_calls
        self.assertEqual(len(star.signal_calls), 1)
        self.assertEqual(star.signal_calls[0]["signal"], "friendly")
        self.assertEqual(star.try_signal_calls, [])


if __name__ == "__main__":
    unittest.main()
